"""A call's shared tail, its argument slot and its summed results, three edits that only pay off together.

A 359-instruction N64 function (KMC GCC 2.7.2 with -fno-strength-reduce, an obstacle-avoiding route chooser) had every
saved register in use, so the compiler spilled two of its parameters to the frame and reloaded one of them at each of
three calls of the same helper. Its saved best had been reached by hand-made frame arithmetic, and each step that
looked natural scored worse until the others were in place (isolated judge, current scoring, hypotheses about why in
brackets):

    saved best                                                      985
    call sums folded (`t = f(a); t = t + g(b);` as `t = f(a) + g(b);`)   720 alone
    parameter slots dropped (see below)                            965 alone
    both of those                                                   700
    shared tails copied into the arms that jump to them          2406 alone (on the saved best)
    slots dropped + tails copied                                    265
    those two + the first arm's `do { .. v = arg; } while (0);` copy forward     80
    all four (the chain child, from the saved best)                    0

Four families, each a bounded proposal for the judge, and a chain child that applies every one that fits:

- `argument_slot_drop`: `volatile s32 padX; volatile s32 spX; ... spX = argN;` (and a plain `spY = argM;` that nothing
  reads) in a function whose parameters live across calls. An agent reproduced the target's `sw $a2, 0xFC($sp)` and
  `lw $a1, 0xFC($sp)` with a volatile member of the frame; the reload is the register allocator's own spill of the
  parameter pseudo (hypothesis: global.c spills the lowest-priority pseudo that has no saved register left), so
  the parameter is used where the slot was, the slot and its padding vanish, and the compiler writes the frame itself.
  A volatile slot also forces its store to be ordered against the other stores, which put the target's two spill stores
  in the opposite order.
- `goto_call_tail_copy`: m2c's `goto block_25;` ... `block_24: var = x; block_25: call(a, var); block_26: return 1;`
  written as each jump's own copy of the tail. GCC 2.7.2's second jump pass cross-jumps the identical tails again
  (hypothesis, as in `join_tail_arm_split_repairs`), and the argument set-up that differs per arm stays in the arm,
  where the target had it (`lw $a1, 0xFC($sp); move $a0, $s2` before each `j`, and the other path's own `lw $a1, 0x104($sp)`).
- `call_result_sum_fold`: `t = f(a); t = t + g(b);` as one expression. The two-statement form copies the first result
  into the variable right after its call; in one expression the copy waits for the second call's argument set-up and
  lands in that call's delay slot, as the target has it (`mov.s $f20, $f0` in the slot of the second `jal`).

- `one_shot_copy_forward`: once the slot is gone, a search's `do { x = f(); v = arg; } while (0);` followed by a use of `v`
  that ends in a return loses its wrapper and the use takes `arg` (the one-shot scope only moved the scheduler's
  boundary: the target's `addiu $v0,$sp,0x98` stood after the call's `addiu $a0,$s2,0x24`).

The goto-copy rewrite changes no control flow: each `goto L;` becomes `{ <statements from L to the next return> }`, and
a label no `goto` reaches any more is dropped, its statements staying where the fall-through reaches them.
"""
import itertools
import re

from .csource import _blank, find
from .pattern_repairs import close

SLOT_FAMILY = 'argument_slot_drop'
TAIL_FAMILY = 'goto_call_tail_copy'
SUM_FAMILY = 'call_result_sum_fold'
FORWARD_FAMILY = 'one_shot_copy_forward'
FAMILY = 'argument_spill_tail'
FAMILIES = (SLOT_FAMILY, TAIL_FAMILY, SUM_FAMILY, FORWARD_FAMILY, FAMILY)

LIMIT = 6
TAIL_STATEMENTS = 4
_KEYWORDS = {'if', 'else', 'while', 'for', 'do', 'switch', 'goto', 'break', 'continue', 'case', 'default', 'typedef',
             'struct', 'union', 'return'}
_LABEL = re.compile(r'(?m)^[ \t]*([A-Za-z_]\w*)[ \t]*:[ \t]*(?=\n|$)')
_INLINE_LABEL = re.compile(r'([A-Za-z_]\w*)[ \t]*:[ \t]*(?=\n|$)', re.M)
_GOTO = re.compile(r'\bgoto\s+(\w+)\s*;')
_ASSIGN = re.compile(r'(?<![=!<>+\-*/%&|^])\b(\w+)\s*=(?!=)')
_SLOT = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<name>[A-Za-z_]\w*)[ \t]*=[ \t]*(?P<param>[A-Za-z_]\w*)[ \t]*;[ \t]*\n')


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    header = clean[span[0]:opening]
    call = re.search(rf'\b{re.escape(name.split("::")[-1])}\s*\(', header)
    params = []
    if call:
        stop = close(header, call.end() - 1)
        for part in (header[call.end():stop - 1] if stop else '').split(','):
            found = re.findall(r'[A-Za-z_]\w*', part)
            if found and found[-1] not in ('void', 'int', 'char', 'short', 'long', 'float', 'double'):
                params.append(found[-1])
    return clean, opening, end, params


def _depth_zero(clean, opening, position):
    return clean[opening + 1:position].count('{') == clean[opening + 1:position].count('}')


# --- argument_slot_drop ------------------------------------------------------------------------------------------------

def slot_variants(source, name):
    """Entry copies of parameters (`slot = arg;`) dropped with their declarations and any unused volatile padding."""
    found = _body(source, name)
    if not found:
        return []
    clean, opening, end, params = found
    body = clean[opening:end]
    edits = []   # (start, stop, replacement) in `source` offsets
    dropped_volatile = False
    for match in _SLOT.finditer(clean, opening, end):
        slot, param = match['name'], match['param']
        if param not in params or slot in params or not _depth_zero(clean, opening, match.start()):
            continue
        declaration = re.search(rf'(?m)^[ \t]*(volatile[ \t]+)?[A-Za-z_][\w \t\*]*?\b{slot}[ \t]*;[ \t]*\n', body)
        if not declaration or declaration.start() > match.start() - opening:
            continue
        assigned = [m for m in _ASSIGN.finditer(body) if m[1] == slot]
        param_assigned = [m for m in _ASSIGN.finditer(body) if m[1] == param]
        if len(assigned) != 1 or param_assigned:
            continue
        if re.search(rf'&\s*{slot}\b|\b{slot}\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=)|(?:\+\+|--)\s*{slot}\b', body):
            continue
        if re.search(rf'&\s*{param}\b|\b{param}\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=)', body):
            continue
        reads = [m for m in re.finditer(rf'\b{slot}\b', body)
                 if opening + m.start() not in range(match.start(), match.end())
                 and not (declaration.start() <= m.start() < declaration.end())]
        edits.append((opening + declaration.start(), opening + declaration.end(), ''))
        edits.append((match.start(), match.end(), ''))
        edits += [(opening + m.start(), opening + m.end(), param) for m in reads]
        dropped_volatile = dropped_volatile or bool(declaration[1])
    if not edits:
        return []
    if dropped_volatile:
        # the padding member that sat beside the slot: a volatile local nothing else names
        for declaration in re.finditer(r'(?m)^[ \t]*volatile[ \t]+[A-Za-z_][\w \t\*]*?\b([A-Za-z_]\w*)[ \t]*;[ \t]*\n', body):
            if len(re.findall(rf'\b{declaration[1]}\b', body)) == 1:
                edits.append((opening + declaration.start(), opening + declaration.end(), ''))
    text = source
    for start, stop, replacement in sorted(set(edits), reverse=True):
        text = text[:start] + replacement + text[stop:]
    return [(SLOT_FAMILY, text)] if text != source else []


# --- goto_call_tail_copy -----------------------------------------------------------------------------------------------

def _tails(clean, source, opening, end):
    """{label: (statements text, labels inside)} for each label whose statements run to a `return` within a few steps."""
    found = {}
    for label in _LABEL.finditer(clean, opening, end):
        if label[1] in _KEYWORDS:
            continue
        position, parts, inside = label.end(), [], []
        while len(parts) <= TAIL_STATEMENTS:
            while position < end and clean[position].isspace():
                position += 1
            nxt = _INLINE_LABEL.match(clean, position)
            if nxt and nxt[1] not in _KEYWORDS:
                inside.append(nxt[1])
                position = nxt.end()
                continue
            stop = clean.find(';', position, end)
            if stop < 0:
                parts = []
                break
            statement = clean[position:stop + 1]
            first = re.match(r'[A-Za-z_]\w*', statement)
            if '{' in statement or '}' in statement or (first and first[0] in _KEYWORDS - {'return'}):
                parts = []
                break
            parts.append(source[position:stop + 1].strip())
            position = stop + 1
            if first and first[0] == 'return':
                break
        else:
            parts = []
        if parts and parts[-1].startswith('return'):
            found[label[1]] = (parts, inside, label.start(), label.end())
    return found


def tail_variants(source, name):
    """Each `goto L;` replaced by a copy of the statements that follow `L:` up to the next return."""
    found = _body(source, name)
    if not found:
        return []
    clean, opening, end, _ = found
    tails = _tails(clean, source, opening, end)
    gotos = [m for m in _GOTO.finditer(clean, opening, end) if m[1] in tails]
    if not gotos:
        return []

    def rewrite(chosen):
        edits = []
        for m in gotos:
            if m[1] in chosen:
                edits.append((m.start(), m.end(), '{\n' + '\n'.join(tails[m[1]][0]) + '\n}'))
        left = {m[1] for m in _GOTO.finditer(clean, opening, end)} - chosen
        for label, (_, inside, start, stop) in tails.items():
            if label in chosen or label in inside:
                if label not in left:
                    edits.append((start, stop, ''))
        text = source
        for start, stop, replacement in sorted(edits, reverse=True):
            text = text[:start] + replacement + text[stop:]
        return text

    labels = sorted({m[1] for m in gotos})
    # a label chained into by another label's statements (block_24 falls into block_25) is copied with it
    out = []
    for chosen in [set(labels)] + [{label} for label in labels]:
        text = rewrite(chosen)
        if text != source and text not in [t for _, t in out]:
            out.append((TAIL_FAMILY, text))
    return out[:LIMIT]


# --- call_result_sum_fold ----------------------------------------------------------------------------------------------

_SUM = re.compile(r'(?P<indent>[ \t]*)(?P<x>[A-Za-z_]\w*)[ \t]*=[ \t]*(?P<a>[A-Za-z_]\w*[ \t]*\([^;{}]*\))[ \t]*;'
                  r'\s*(?P=x)[ \t]*(?:=[ \t]*(?P=x)[ \t]*(?P<op>[-+*])|(?P<aug>[-+*])=)[ \t]*'
                  r'(?P<b>[A-Za-z_]\w*[ \t]*\([^;{}]*\))[ \t]*;')


def sum_variants(source, name):
    """`t = f(a); t = t + g(b);` as `t = f(a) + g(b);`."""
    found = _body(source, name)
    if not found:
        return []
    clean, opening, end, _ = found
    edits = []
    for m in _SUM.finditer(clean, opening, end):
        if re.fullmatch(r'(?:if|while|for|switch|return|sizeof)', m['a'].split('(')[0].strip()):
            continue
        if re.search(rf'\b{m["x"]}\b', m['b']) or re.search(rf'\b{m["x"]}\b', m['a']):
            continue
        operator = m['op'] or m['aug']
        edits.append((m.start(), m.end(), f'{m["indent"]}{m["x"]} = {source[m.start("a"):m.end("a")]} {operator} '
                                          f'{source[m.start("b"):m.end("b")]};'))
    if not edits:
        return []
    text = source
    for start, stop, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[stop:]
    return [(SUM_FAMILY, text)]


# --- one_shot_copy_forward ---------------------------------------------------------------------------------------------

_WRAPPER = re.compile(r'do[ \t]*\{(?P<body>[^{}]*)\}[ \t]*while[ \t]*\([ \t]*0[ \t]*\)[ \t]*;')


def forward_variants(source, name):
    """`do { x = f(); v = arg; } while (0);` then `call(.., v); return ..;`: the wrapper dropped, the call given `arg`.

    The wrapper was a search's way to keep a parameter copy where the read of a volatile slot sat; with the slot gone
    the copy is a plain forward, and the one-shot scope around the other statements only moves the scheduler's
    boundary (the target's `addiu $v0,$sp,0x98` before the call's `addiu $a0,$s2,0x24` came back without it)."""
    found = _body(source, name)
    if not found:
        return []
    clean, opening, end, params = found
    edits = []
    for wrapper in _WRAPPER.finditer(clean, opening, end):
        statements = [part for part in re.split(r';', clean[wrapper.start('body'):wrapper.end('body')]) if part.strip()]
        last = re.fullmatch(r'\s*([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*', statements[-1]) if statements else None
        if not last or last[2] not in params or last[1] in params:
            continue
        var, param = last[1], last[2]
        depth, position = 0, wrapper.end()
        while position < end:
            depth += (clean[position] == '{') - (clean[position] == '}')
            if depth < 0:
                break
            position += 1
        region = clean[wrapper.end():position]
        later = [m for m in re.finditer(rf'\b{var}\b', region)]
        assigned = _ASSIGN.search(region) if any(m[1] == var for m in _ASSIGN.finditer(region)) else None
        ends = re.search(r'\breturn\b[^;{}]*;\s*$', region)
        if (not later or assigned or not ends or _LABEL.search(region)
                or any(m[1] == param for m in _ASSIGN.finditer(region))
                or re.search(rf'&\s*{var}\b', clean[opening:end])):
            continue
        kept = source[wrapper.start('body'):wrapper.end('body')]
        kept = kept[:kept.rstrip().rfind(';', 0, len(kept.rstrip()) - 1) + 1].strip() if len(statements) > 1 else ''
        for m in later:
            edits.append((wrapper.end() + m.start(), wrapper.end() + m.end(), param))
        edits.append((wrapper.start(), wrapper.end(), kept))
    if not edits:
        return []
    text = source
    for start, stop, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[stop:]
    return [(FORWARD_FAMILY, text)]


# --- the chain ---------------------------------------------------------------------------------------------------------

def variants(source, name):
    """The three edits one at a time, every combination of those that fit, and the chain of all of them."""
    steps = ((SLOT_FAMILY, slot_variants), (FORWARD_FAMILY, forward_variants), (TAIL_FAMILY, tail_variants),
             (SUM_FAMILY, sum_variants))
    dropped = (slot_variants(source, name) or [(None, source)])[0][1]   # the copy forward reads what the slot drop leaves
    fits = [i for i, (_, step) in enumerate(steps) if step(source, name) or step(dropped, name)]
    out = []
    seen = {source}

    def add(family, text):
        if text not in seen:
            seen.add(text)
            out.append((family, text))

    for size in range(len(fits), 0, -1):
        for subset in itertools.combinations(fits, size):
            text, used = source, []
            for i in subset:
                produced = steps[i][1](text, name)
                if produced:
                    text = produced[0][1]
                    used.append(i)
            if used:
                add(FAMILY if len(used) > 1 else steps[used[0]][0], text)
    # the per-label tail copies beyond the broadest one, after the slots are dropped
    slot = slot_variants(source, name)
    for _, text in tail_variants(slot[0][1] if slot else source, name)[1:]:
        add(FAMILY if slot else TAIL_FAMILY, text)
    return out

"""A label in the middle of a block whose run ends in a `goto`, copied in place of an earlier `goto` to it.

m2c writes a shared push-out tail once, behind a label that follows the other arm's own statements, and sends the
earlier arm there with a `goto`:

    if (d < limit) { ..; p0 += s0; p1 += s1; p2 += s2; goto tail; } } goto next; }
    ..
    f = r - dot; s0 = f * n0; ..; p0 += s0; ..;
    tail: if (flags & 2) { rotate(m, &s0); } out->x += s0; ..; hit = 1; goto next;

The compiler's jump pass (jump.c cross-jumping, after reload) merges two identical runs that end in the same jump, so
a copy written in the earlier arm comes out as the target's `j tail` anyway. What it changes is reload: the copy is
still reloaded before it is deleted, and reload1.c `allocate_reload_reg` hands out the spill registers round robin
(`last_spill_reg`), one turn per reload, in insn order. A copy with an odd number of reloads (a spilled argument's
loads, a constant's register) flips every later `$t1`/`$t2` choice. A 2,267-instruction collision sweep (KMC GCC 2.7.2,
`-G0 -mips3 -mgp32 -mfp32 -O2`) had every spill register from its u8 site's return block on exchanged; the tail copy
(three reloads) turned them back, and the walk after it then needed one turn more, which `loop_break_return` gives
(195 -> 30 with both; the copy alone, 1521, flips the walk's registers the wrong way and moves two float arguments'
global.c tie). So each copy is offered alone and with each of `loop_break_return`'s children.

mid_label_run_copy
    A label preceded by `;` or `}` (not the head of its block), whose run (the statements after it, to the first
    `goto M;` at the label's brace depth) holds no other label, no `return` and no `break`/`continue`: each
    `goto label;` statement outside the run is replaced by the run. The label stays while other `goto`s reach it.
    Children: one per `goto`, each also combined with the `loop_break_return` children of the copied source.
    At most 6.

tail_label_run_copy
    The same copy where the labelled run ends no `goto` but runs out of a `void` function: only closing braces of `if`,
    `else` or bare blocks (and the `else` arms the flow skips) follow it. Each `goto label;` becomes `{ run return; }`.
    m2c writes `v = X; goto call;` arms around one `call: *p = f(v);`, which the game wrote as a call in every arm
    (jump.c merges the tails again after register allocation, but the arguments' pseudos live on). A 95-instruction
    angle picker (KMC GCC 2.7.2) sat at 60 with float registers exchanged: the copies (370), `local_web_split` on the
    value (325), then `local_width_group` reached 0. Children: every `goto` at once, that with each `local_web_split`
    child, then each `goto` alone. At most 6.

Candidate rewrites; the exact judge decides each (the rotation is read in reload1.c; the match is one function).
"""
import re

from .flag_exit_repairs import BREAK_RETURN
from .flag_exit_repairs import variants as _flag_exit_variants
from .integer_repair_support import IDENT, view
from .local_web_split import variants as _web_variants
from .pattern_repairs import close

FAMILY = 'mid_label_run_copy'
TAIL_FAMILY = 'tail_label_run_copy'
FAMILIES = (FAMILY, TAIL_FAMILY)
LIMIT = 6
RUN_LIMIT = 4000
_LABEL = re.compile(rf'(?<=[;}}])(\s*)({IDENT})\s*:(?!:)')


def _run(clean, start, end):
    """End offset (after `goto M;`) of the run that starts at start, or None."""
    depth = 0
    i = start
    while i < end:
        ch = clean[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and clean.startswith('goto', i) and not re.match(r'\w', clean[i - 1]):
            hit = re.compile(rf'goto\s+{IDENT}\s*;').match(clean, i)
            if hit:
                return hit.end()
        i += 1
    return None


def _copies(source, part):
    clean = part.clean
    out = []
    for hit in _LABEL.finditer(clean, part.opening + 1, part.end):
        name = hit[2]
        if name in ('default', 'case'):
            continue
        start = hit.end()
        stop = _run(clean, start, part.end)
        if stop is None or stop - start > RUN_LIMIT:
            continue
        run = clean[start:stop]
        if re.search(rf'\b(?:return|break|continue|case|default)\b|(?<![:\w]){IDENT}\s*:(?!:)', run):
            continue
        site_pattern = re.compile(rf'(?<=[;{{}}])(\s*)goto\s+{re.escape(name)}\s*;')
        sites = [m for m in site_pattern.finditer(clean, part.opening, part.end) if not start <= m.start() < stop]
        if not sites:
            continue
        text = source[start:stop].strip()
        for site in sites:
            lo = site.start() + len(site[1])
            edited = source[:lo] + text + source[site.end():]
            if not re.search(rf'goto\s+{re.escape(name)}\s*;', edited):
                edited = re.sub(rf'(?<=[;}}])(\s*){re.escape(name)}\s*:(?!:)', r'\1', edited, count=1)
            out.append(edited)
            if len(out) >= LIMIT:
                return out
    return out


def _plain_block(clean, opening):
    """Whether the `{` at opening belongs to an `if`, an `else` or no statement: leaving it just falls on."""
    head = clean[:opening].rstrip()
    if head.endswith(('{', '}', ';', ':')) or re.search(r'\belse$', head):
        return True
    if not head.endswith(')'):
        return False
    depth = 0
    for i in range(len(head) - 1, -1, -1):
        depth += (head[i] == ')') - (head[i] == '(')
        if not depth:
            return re.search(r'\bif\s*$', head[:i]) is not None
    return False


def _skip_else(clean, i, end):
    """Past the `else` chain at i, if one is there; None when an arm has no braces to measure."""
    while True:
        hit = re.compile(r'\s*else\b\s*').match(clean, i)
        if not hit:
            return i
        i = hit.end()
        condition = re.compile(r'if\s*').match(clean, i)
        if condition:
            stop = close(clean, condition.end())
            if not stop:
                return None
            i = re.compile(r'\s*').match(clean, stop).end()
        if i >= end or clean[i] != '{':
            return None
        i = close(clean, i, '{', '}')
        if not i:
            return None


def _tail_end(clean, part, start):
    """Where the run at start closes its block, when control then only leaves the function; else None."""
    opened = []
    for i in range(part.opening, start):
        if clean[i] == '{':
            opened.append(i)
        elif clean[i] == '}':
            opened.pop()
    if not opened:
        return None
    stop = close(clean, opened[-1], '{', '}') - 1
    i = stop
    while len(opened) > 1:
        if not _plain_block(clean, opened[-1]):
            return None
        i = close(clean, opened.pop(), '{', '}')
        i = _skip_else(clean, i, part.end)
        if i is None:
            return None
        i = re.compile(r'[\s;]*').match(clean, i).end()
        if i >= len(clean) or clean[i] != '}':
            return None
    return stop


def _tail_copies(source, name):
    """(every goto replaced, then each alone) for each label whose run leaves a void function."""
    part = view(source, name)
    if not part or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(', part.clean[:part.opening]):
        return []
    clean = part.clean
    out = []
    for hit in _LABEL.finditer(clean, part.opening + 1, part.end):
        label = hit[2]
        if label in ('default', 'case'):
            continue
        start = hit.end()
        stop = _tail_end(clean, part, start)
        if stop is None or not 0 < stop - start <= RUN_LIMIT:
            continue
        run = clean[start:stop]
        if not run.strip() or re.search(rf'\b(?:return|break|continue|goto|case|default)\b|(?<![:\w]){IDENT}\s*:(?!:)', run):
            continue
        gotos = re.compile(rf'\bgoto\s+{re.escape(label)}\s*;')
        sites = [m for m in gotos.finditer(clean, part.opening, part.end) if not start <= m.start() < stop]
        if not sites:
            continue
        text = '{ ' + source[start:stop].strip() + ' return; }'
        edited = source
        for site in reversed(sites):
            edited = edited[:site.start()] + text + edited[site.end():]
        edited = re.sub(rf'(?<=[;{{}}])(\s*){re.escape(label)}\s*:(?!:)', r'\1', edited, count=1)
        out.append(edited)
        if len(sites) > 1:
            out += [source[:site.start()] + text + source[site.end():] for site in sites]
    return out


def _tail_variants(source, name):
    copies = _tail_copies(source, name)
    if not copies:
        return []
    out = [copies[0]] + [child for _, child in _web_variants(copies[0], name)] + copies[1:]
    return [(TAIL_FAMILY, text) for text in out[:LIMIT]]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for copy in _copies(source, part):
        out.append((FAMILY, copy))
        for family, child in _flag_exit_variants(copy, name):
            if family == BREAK_RETURN:
                out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out[:LIMIT] + _tail_variants(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring

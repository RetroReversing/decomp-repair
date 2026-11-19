"""A call's argument count from the target's own setup of the argument registers before it.

m2c guesses a callee's arity from what the caller seems to set up, and a constant it misses leaves the call one
argument short: an N64 function created its message queues with `osCreateMesgQueue(&q, msgs)` where the game wrote
`addiu $a2, $zero, 8` before each `jal`. The other way round, a draft passes a trailing argument the game never set.
For each callee, the target's calls (in order) say which of `$a0`-`$a3` were written before the `jal` or in its delay
slot; the C's calls to it, when there are as many, get the missing trailing arguments the target set to constants,
or lose the trailing ones the target never set. A prototype with parameters gains or loses the same ones.
"""
import re

from . import m2cfix
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'target_call_arity'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
LINE = re.compile(r'^\s*(?:/\*.*?\*/)?\s*(?P<op>[a-z][\w.]*)\s*(?P<args>[^\n]*)$')
ARGREG = ('a0', 'a1', 'a2', 'a3')
NOT_CALLS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'M2C_FIELD', 'M2C_ERROR', 'M2C_BITWISE', 'do'}


def _instructions(asm):
    for line in (asm or '').splitlines():
        m = LINE.match(line)
        if m and not line.strip().startswith(('.', 'glabel', 'endlabel')) and not m['op'].endswith(':'):
            yield m['op'], m['args'].strip()


def calls(asm):
    """[(callee, {register: constant or None})] for each `jal`, in order: the argument registers written since the
    previous call or branch target, and in the delay slot."""
    found = []
    written = {}
    pending = None
    for op, args in _instructions(asm):
        dest = re.match(r'\$(\w+)', args)
        if pending is not None:  # the delay slot
            if dest and dest[1] in ARGREG and not op.startswith(('s', 'b', 'j')):
                written[dest[1]] = _constant(op, args)
            found.append((pending, written))
            pending, written = None, {}
            continue
        if op == 'jal':
            pending = args.split('+')[0].strip()
            continue
        store = op.startswith(('sw', 'sh', 'sb', 'sd', 'swc1', 'sdc1'))
        # (an argument register read into a register that isn't one is a temporary, not an argument: an N64
        # function's `mfhi $a2` then `subu $v1, $a2, $v1` divided by three, and its calls took one argument)
        if dest and not store and dest[1] not in ARGREG and not op.startswith(('b', 'j')):
            for read in re.findall(r'\$(\w+)', args)[1:]:
                if read in ARGREG and read != dest[1]:
                    written.pop(read, None)
        if dest and dest[1] in ARGREG and not store:
            written[dest[1]] = _constant(op, args)
    return found


def _constant(op, args):
    m = re.fullmatch(r'\$\w+\s*,\s*\$zero\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))', args)
    if op in ('addiu', 'ori', 'daddiu') and m:
        return int(m[1], 0)
    if op == 'move' and re.fullmatch(r'\$\w+\s*,\s*\$zero', args):
        return 0
    if op in ('addu', 'or', 'daddu') and re.fullmatch(r'\$\w+\s*,\s*\$zero\s*,\s*\$zero', args):
        return 0  # (`move $a0, $zero` as some assemblers write it)
    return None


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    jals = calls(asm)
    targets = {}
    for callee, regs in jals:
        targets.setdefault(callee, []).append(regs)
    every = [m for m in re.finditer(r'\b(' + IDENT + r')\s*\(', clean[opening:end]) if m[1] not in NOT_CALLS]
    sites = {}
    # (the target's assembly may name a callee by its address, `func_800A1BB0`, where the C has its symbol: when
    # the C makes as many calls as the target and every name both share sits at the same place, pair them in order)
    by_order = len(every) == len(jals) and all(m[1] == j[0] for m, j in zip(every, jals) if m[1] in targets)
    for k, m in enumerate(every):
        if m[1] in targets or by_order:
            sites.setdefault(m[1], []).append(opening + m.end() - 1)
            if by_order and m[1] not in targets:
                targets.setdefault(('order', m[1]), []).append(jals[k][1])
    targets = {k[1] if isinstance(k, tuple) else k: v for k, v in targets.items()}
    result = []
    for callee, parens in sites.items():
        wanted = targets[callee]
        if len(parens) != len(wanted):
            continue
        add, drop = [], []
        for paren, regs in zip(parens, wanted):
            closing = close(clean, paren)
            inner = clean[paren + 1:closing - 1]
            args = [a for a in m2cfix._split_top_level(inner)] if inner.strip() else []
            count = max((ARGREG.index(r) + 1 for r in regs), default=0)
            if len(args) < count <= 4:
                missing = [regs.get(ARGREG[i]) for i in range(len(args), count)]
                if any(v is None for v in missing):
                    add = None
                elif add is not None:
                    add.append((closing - 1, ''.join((', ' if (args or k) else '') + _number(v)
                                                     for k, v in enumerate(missing))))
            elif count < len(args) <= 4 and add == []:
                drop.append((paren + 1 + _offset(inner, count), closing - 1))
        for edits, change in ((add, 'add'), (drop if len(drop) == len(parens) else None, 'drop')):
            if not edits:
                continue
            text = source
            for a, b_or_text in sorted(edits, reverse=True, key=lambda e: e[0]):
                if change == 'add':
                    text = text[:a] + b_or_text + text[a:]
                else:
                    text = text[:a] + text[b_or_text:]
            text = _prototype(text, callee, name, change, edits, clean, parens)
            if text and text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:4]


def _number(value):
    return f'0x{value:X}' if value > 9 else str(value)


def _offset(inner, count):
    """Where the argument after the first `count` ends in `inner` (the comma before it included)."""
    depth = 0
    seen = 0
    for i, ch in enumerate(inner):
        depth += (ch in '([{') - (ch in ')]}')
        if depth == 0 and ch == ',':
            seen += 1
            if seen == count:
                return i if count else 0
    return 0 if count == 0 else len(inner)


def _prototype(text, callee, name, change, edits, clean, parens):
    """The callee's prototype changed to match, when it lists parameters; unchanged for `()` or none."""
    clean = _blank(text)
    span = find(text, name)
    outside_end = span[0] if span else len(text)
    proto = re.search(r'(?m)^[^\n;{}]*\b' + re.escape(callee) + r'\s*\(([^()]*)\)\s*;', clean[:outside_end])
    if not proto or not proto[1].strip() or proto[1].strip() == '...' or '...' in proto[1]:
        return text
    params = [p.strip() for p in proto[1].split(',')] if proto[1].strip() != 'void' else []
    call = re.search(r'\b' + re.escape(callee) + r'\s*\(', clean[span[0]:] if span else '')
    if not call:
        return text
    at = span[0] + call.end() - 1
    inner = clean[at + 1:close(clean, at) - 1]
    count = len(m2cfix._split_top_level(inner)) if inner.strip() else 0
    if change == 'add':
        params = params + ['s32'] * (count - len(params))
    else:
        params = params[:count]
    new = ', '.join(params) if params else 'void'
    return text[:proto.start(1)] + new + text[proto.end(1):]

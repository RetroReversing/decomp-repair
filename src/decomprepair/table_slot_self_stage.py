"""A pointer read from a table of pointers, with the slot's address staged in the pointer itself.

`verts = TABLE[o->model];` is one pseudo set once: GCC's first scheduler (sched.c `birthing_insn_p`) launches the
slot's address sum, a single-set pseudo, right before the load that reads it, so the `addu` of `&TABLE[m]` sits late in
the block. Written in two steps through the same local,

    verts = (MVtx16 *) &TABLE[o->model];
    verts = *(MVtx16 **) verts;

the local is set twice, the sum is no longer a birthing insn and it is scheduled where the target has it, next to the
other table's sum that shares the `m * 4` (`sll`; `addu $a1, $a0, $t2`; `addu $a0, $a0, $v0`). On two N64 triangle-table
walkers (SN64 GCC 2.8.1, `-mfp32`) it was the step loop.c and the scheduler needed together: a 438-instruction ray test
went 210 -> 55 with the triangle pointer staged in place (`tri = (Tri *) &T[m]; tri = &(*(Tri **) tri)[k];`), and a
761-instruction one reached the target's loop-head schedule (only registers left) with the vertex pointer staged and
moved after the triangle pointer's statement. The scheduler reading is from gcc-2.8.1's sched.c; that it is what decides
these rows is a hypothesis the measurements agree with, and the judge decides each child.

Children (`table_slot_self_stage`, bounded): for each statement `V = SYM[E];`, `V = SYM[E] + K;` or `V = &SYM[E][K];`
whose `V` is a local declared `T *V` (one level of pointer) and whose `E`/`K` name neither `V` nor contain a call or an
assignment, the staged statement in place, and the staged statement moved after the next simple statement when that one
does not name `V` (the order the second walker needed).
"""
import re

from .csource import _blank, find

FAMILY = 'table_slot_self_stage'
FAMILIES = (FAMILY,)
LIMIT = 8
IDENT = r'[A-Za-z_]\w*'


def variants(source, name):
    return [(FAMILY, text) for text in stages(source, name)]


def _bracket(text, at):
    """The index of the `]` closing the `[` at `at`, or -1."""
    depth = 0
    for i in range(at, len(text)):
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
            if depth == 0:
                return i
        elif text[i] in ';{}':
            return -1
    return -1


def _plain(expr, var):
    return (not re.search(rf'(?<![\w.>]){re.escape(var)}\b', expr) and not re.search(rf'{IDENT}\s*\(', expr)
            and not re.search(r'(?<![=!<>])=(?!=)|\+\+|--', expr))


def _staged(var, kind, sym, index, rest):
    """The two statements for one shape (kind: 'load', 'sum' or 'element')."""
    first = f'{var} = ({kind[1]} *) &{sym}[{index}];'
    if kind[0] == 'load':
        second = f'{var} = *({kind[1]} **) {var};'
    elif kind[0] == 'sum':
        second = f'{var} = *({kind[1]} **) {var} {rest};'
    else:
        second = f'{var} = &(*({kind[1]} **) {var})[{rest}];'
    return first, second


def stages(source, name):
    clean = _blank(source)
    span = find(source, name)
    if not span or re.search(r'\b(?:volatile|asm|__asm__)\b', clean[span[0]:span[1]]):
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    body = clean[opening:end]
    types = {}
    for hit in re.finditer(rf'(?m)^\s*(?:const\s+)?({IDENT})\s*\*\s*({IDENT})\s*;', body):
        if hit[1] not in ('return', 'goto', 'else'):
            types.setdefault(hit[2], hit[1])
    result = []
    for hit in re.finditer(rf'(?m)^([ \t]*)({IDENT})\s*=\s*(&\s*)?({IDENT})\s*\[', body):
        var, amp, sym = hit[2], hit[3], hit[4]
        if var not in types or sym == var or sym in types:
            continue
        at = opening + hit.start(2)
        open_at = opening + hit.end() - 1
        close = _bracket(clean, open_at)
        if close < 0:
            continue
        index = source[open_at + 1:close].strip()
        tail_end = clean.find(';', close)
        if tail_end < 0 or not _plain(clean[open_at + 1:close], var):
            continue
        tail = clean[close + 1:tail_end].strip()
        if amp:
            element = re.fullmatch(r'\[(.*)\]', tail, re.S)
            if not element or not _plain(element[1], var) or _bracket(tail, 0) != len(tail) - 1:
                continue
            kind, rest = ('element', types[var]), source[close + 1:tail_end].strip()[1:-1].strip()
        elif not tail:
            kind, rest = ('load', types[var]), ''
        elif re.fullmatch(r'[+-][^?:]*', tail) and _plain(tail[1:], var) and tail.count('[') == tail.count(']'):
            kind, rest = ('sum', types[var]), source[close + 1:tail_end].strip()
        else:
            continue
        first, second = _staged(var, kind, sym, index, rest)
        indent = hit[1]
        stmt_end = tail_end + 1
        line_end = stmt_end + re.match(r'[ \t]*\n?', source[stmt_end:]).end()
        texts = [source[:at] + first + '\n' + indent + second + source[stmt_end:]]
        nxt = re.match(rf'([ \t]*)({IDENT})\s*=[^;{{}}]*;[ \t]*\n', source[line_end:])
        if nxt and not re.search(rf'(?<![\w.>]){re.escape(var)}\b', nxt[0]) and nxt[2] != var:
            moved = source[line_end:line_end + nxt.end()]
            line_start = at - len(indent)
            texts.append(source[:line_start] + moved + indent + first + '\n' + indent + second + '\n'
                         + source[line_end + nxt.end():])
        for text in texts:
            if text != source and text not in result:
                result.append(text)
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)

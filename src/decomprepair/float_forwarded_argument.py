"""Restore a float argument that the target forwards to two joined calls."""

import re

from .goto_structure_repairs import _paths, parse
from .integer_repair_support import IDENT, edit, view
from .mips_returns import instructions
from .pattern_repairs import close

FAMILY = 'float_forwarded_argument'
FAMILIES = (FAMILY,)
_FLOAT = r'(?:f32|float)'
_SINK = re.compile(rf'({IDENT})\(\s*({IDENT}),\s*({IDENT}),\s*({IDENT})\s*\)\s*;')
_PRODUCER = re.compile(rf'({IDENT})\s*=\s*({IDENT})\(\s*\)\s*;')
_FORWARD = re.compile(r'mov\.s\s+\$(?:f12|fa0),\s*(\$f\w+)')


def _has_forwarded_register(rows, producer, sink):
    calls = [index for index, row in enumerate(rows[:-1]) if row == f'jal {producer}']
    if len(calls) != 1:
        return False
    at = calls[0]
    if not (forward := _FORWARD.fullmatch(rows[at+1])):
        return False
    window = rows[at+2:at+8]
    sink_at = next((index for index, row in enumerate(window) if row.startswith(('jal ', 'jalr '))), None)
    if sink_at is None or window[sink_at] != f'jal {sink}':
        return False
    prepare = window[:sink_at]
    return (f'mfc1 $a1, {forward[1]}' in prepare
            and any(row in ('mfc1 $a2, $f0', 'mfc1 $a2, $fv0') for row in prepare))


def _prototype(part, producer, before):
    pattern = rf'(?m)^\s*(?:extern\s+)?{_FLOAT}\s+{producer}\(\s*(void)\s*\)\s*;'
    declarations = list(re.finditer(pattern, part.clean[:before]))
    return declarations[0] if len(declarations) == 1 else None


def _direct_arm(branch):
    return branch and branch['block'] and branch['stmts']


def _candidate(part, source, rows, branch, continuation, before):
    if branch.kind != 'if' or continuation.kind != 'simple':
        return None
    then = _direct_arm(branch.parts['then'])
    other = _direct_arm(branch.parts['other'])
    if not then or not other:
        return None
    sink = _SINK.fullmatch(part.clean[continuation.start:continuation.end])
    producer = _PRODUCER.fullmatch(part.clean[other[-1].start:other[-1].end])
    if not sink or not producer or sink[4] != producer[1]:
        return None
    zero = next((stmt for stmt in then if re.fullmatch(
        rf'{producer[1]}\s*=\s*0\.0[fF]\s*;', part.clean[stmt.start:stmt.end])), None)
    if not zero or not _has_forwarded_register(rows, producer[2], sink[1]):
        return None
    if len(re.findall(rf'\b{producer[2]}\s*\(', part.clean)) != 2:
        return None
    if any(stmt.kind in {'goto', 'jump', 'label', 'case'} or re.search(
        r'\b(?:goto|return|break|continue)\b', part.clean[stmt.start:stmt.end]) for stmt in then + other):
        return None
    names = (producer[1], sink[3])
    if any(len(re.findall(rf'(?m)^[ \t]*{_FLOAT}\s+{name}\s*;', part.body)) != 1
           or re.search(rf'&\s*\(*\s*{name}\b', part.body) for name in names):
        return None
    if len(re.findall(rf'\b{producer[1]}\b', part.body)) != 4:
        return None
    proto = _prototype(part, producer[2], before)
    if not proto:
        return None

    args = f'{sink[2]}, {sink[3]}'
    zero_call = f'{sink[1]}({args}, 0.0f);'
    init_call = f'{producer[1]} = {producer[2]}({sink[3]});'
    column = then[-1].start - source.rfind('\n', 0, then[-1].start) - 1
    then_end = then[-1].end
    zero_edits = [(zero.start, then_end, zero_call)] if zero is then[-1] else [
        (zero.start, zero.end, ''), (then_end, then_end, '\n' + ' ' * column + zero_call)]
    return edit(source, [(*proto.span(1), 'f32'),
                         *zero_edits,
                         (other[-1].start, other[-1].end, init_call + '\n' + ' ' * column
                          + source[continuation.start:continuation.end]),
                         (continuation.start, continuation.end, '')])


def variants(source, name, asm):
    part = view(source, name) if asm and 'mov.s' in asm and 'mfc1' in asm else None
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    try:
        paths = list(_paths(parse(part.clean, part.opening+1, end-1)))
    except ValueError:
        return []
    rows = instructions(asm)
    before = part.clean.rfind('\n', 0, part.opening)
    choices = []
    for stmt, trail in paths:
        siblings, index, _ = trail[-1]
        if stmt.kind != 'if' or index + 1 == len(siblings):
            continue
        candidate = _candidate(part, source, rows, stmt, siblings[index+1], before)
        if candidate:
            choices.append((FAMILY, candidate))
    return choices[:3]

"""Capture the next projection input before the measured first-result store."""

import re

from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _visible
from .wide_update_before_flags import _FPR, _record_field

FAMILY = 'projection_argument_before_store'
_FIELD = r'\*[^;={}\n]+?'
_SCALE = r'\d+\.\d+[fF]'
_HIGH = re.compile(rf'lui \$at, %hi\(({IDENT})\)')
_CALL = re.compile(rf'jal ({IDENT})')
_STORE = re.compile(rf'swc1 ({_FPR}), ({NUMBER})\((\$\w+)\)')
_SOURCE = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)(?P<first>{_FIELD})\s*=\s*'
    rf'(?P<expr>\(\s*(?P<type>f32|float)\s*\)\s*\(\s*\(\s*{IDENT}\s*\+\s*\(\s*(?P<input1>{_FIELD})\s*\)'
    rf'\s*\)\s*\+\s*\(\s*(?P<call1>{IDENT})\(\s*(?P<arg>{IDENT})\s*\)\s*\*\s*(?P<scale>{_SCALE})\s*\)\s*\))\s*;\n'
    rf'(?P=pad)(?P<second>{_FIELD})\s*=\s*\(\s*(?P=type)\s*\)\s*\(\s*\(\s*{IDENT}\s*\+\s*'
    rf'\(\s*(?P<input2>{_FIELD})\s*\)\s*\)\s*\+\s*\(\s*(?P<call2>{IDENT})\(\s*(?P<arg2>(?P=arg))\s*\)'
    rf'\s*\*\s*(?P=scale)\s*\)\s*\)\s*;'
)


def _evidence(rows):
    targets = [(index, left) for index, (_, left, _) in enumerate(rows) if left]
    witnesses = set()
    for i in range(3, len(targets) - 3):
        _, high = targets[i]
        address = _HIGH.fullmatch(high)
        call = _CALL.fullmatch(targets[i + 2][1])
        store = _STORE.fullmatch(targets[i + 3][1])
        if not (address and call and store):
            continue
        symbol, reg = address[1], store[1]
        low = f'lwc1 $f12, %lo({symbol})($at)'
        if targets[i + 1][1] != low or targets[i - 1][1] != f'add.s {reg}, {reg}, $f0':
            continue
        begin, finish = targets[i - 1][0], targets[i + 3][0]
        candidate = [right for _, _, right in rows[begin:finish + 1] if right]
        if candidate != [targets[i - 1][1], store[0], high, call[0], low]:
            continue
        previous = targets[max(0, i - 24):i - 2]
        first = next(((position, row, match) for position, (row, line) in reversed(list(enumerate(previous)))
                      if (match := _CALL.fullmatch(line))), None)
        if not first:
            continue
        j, call_row, first_call = first
        if (j == 0 or j + 1 >= len(previous) or first_call[1] == call[1] or rows[call_row][2] != first_call[0]
                or previous[j - 1][1] != high or previous[j + 1][1] != low):
            continue
        for row, line in targets[i + 4:i + 19]:
            last = _STORE.fullmatch(line)
            if not last or rows[row][2] != line or last[3] != store[3]:
                continue
            first_offset, second_offset = integer(store[2]), integer(last[2])
            if first_offset != second_offset and first_offset % 4 == second_offset % 4 == 0:
                witnesses.add((first_call[1], call[1], symbol, first_offset, second_offset))
                break
    return witnesses


def variants(source, name, rows, *, header=''):
    witnesses = _evidence(rows)
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    prefix = part.clean[:part.opening]
    result = fresh(source, header, 'repair_projection_value')
    argument = fresh(source, header, 'repair_projection_argument')
    proposals = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        first, second, input1, input2 = (
            _record_field(m[key], prefix, 'float') for key in ('first', 'second', 'input1', 'input2')
        )
        if not first or not second or not input1 or not input2 or first[0] != second[0] or input1[0] != input2[0]:
            continue
        if (m['call1'], m['call2'], m['arg'], first[1], second[1]) not in witnesses:
            continue
        if (not re.search(rf'\bextern\s+(?:const\s+)?{m["type"]}\s+{m["arg"]}\s*;', context)
                or macros & set(re.findall(IDENT, m[0])) or re.search(r'/[*/]|#', source[m.start():m.end()])):
            continue
        prior = part.clean[part.opening + 1:m.start()].rstrip()
        if prior and prior[-1] not in ';{}:':
            continue
        pad, kind = m['pad'], m['type']
        capture = (f'{pad}{{ {kind} {result}; {kind} {argument};\n'
                   f'{pad}{result} = {m["expr"]};\n{pad}{argument} = {m["arg"]};\n')
        proposals.append((FAMILY, edit(source, [
            (m.start(), m.start(), capture),
            (*m.span('expr'), result),
            (*m.span('arg2'), argument),
            (m.end(), m.end(), f'\n{pad}}}'),
        ])))
        if len(proposals) == 4:
            break
    return proposals

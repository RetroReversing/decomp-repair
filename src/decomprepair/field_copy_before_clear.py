"""Read a field before the second clear of a measured call setup."""

import re

from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _visible
from .wide_update_before_flags import _FPR, _record_field

FAMILY = 'field_copy_before_clear'
_FIELD = r'\*[^;={}\n]+?'
_ZERO = re.compile(rf'sw \$zero, ({NUMBER})\((\$\w+)\)')
_LOAD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})\((\$\w+)\)')
_STORE = re.compile(rf'swc1 ({_FPR}), ({NUMBER})\((\$\w+)\)')
_CALL = re.compile(rf'jal ({IDENT})')
_SOURCE = re.compile(
    rf'(?m)^[ \t]*(?P<first>{_FIELD})\s*=\s*0\.0[fF]\s*;\s*'
    rf'(?:(?P<record>{IDENT})\s*\.\s*{IDENT}\s*=\s*0[uU]?\s*;\s*)?'
    rf'^(?P<pad>[ \t]*)(?P<second>{_FIELD})\s*=\s*(?:0\.0[fF]|(?P=record)\s*\.\s*{IDENT})\s*;\s*'
    rf'(?P<out>{_FIELD})\s*=\s*\((?P<type>f32|float)\)\s*(?P<read>\(\s*(?P<field>{_FIELD})\s*\))\s*;\s*'
    rf'(?P<call>{IDENT})\(\s*(?P<first_arg>{IDENT})\s*,\s*(?P<argument>{NUMBER})\s*\)\s*;'
)


def _witnesses(rows):
    targets = [(index, left) for index, (_, left, _) in enumerate(rows) if left]
    shapes = set()
    for i in range(len(targets) - 6):
        index, op = targets[i]
        group = [left for _, left in targets[i:i + 7]]
        first, load, second, call, write = (
            _ZERO.fullmatch(op), _LOAD.fullmatch(group[1]), _ZERO.fullmatch(group[4]),
            _CALL.fullmatch(group[5]), _STORE.fullmatch(group[6]),
        )
        if not (first and load and second and write and call):
            continue
        if not first[2] == second[2] == write[3] or load[1] != write[1] or load[3] == first[2]:
            continue
        first_offset, second_offset, copy_offset = map(integer, (first[1], second[1], write[2]))
        if len({first_offset, second_offset, copy_offset}) != 3 or any(
            offset % 4 for offset in (first_offset, second_offset, copy_offset)
        ):
            continue
        argument = re.fullmatch(rf'addiu \$a1, \$zero, ({NUMBER})', group[3])
        if group[2] != f'move $a0, {first[2]}' or not argument:
            continue
        end = targets[i + 6][0]
        candidate = [right for _, _, right in rows[index:end + 1] if right]
        if candidate == [group[0], group[4], *group[1:4], *group[5:]]:
            shapes.add((first_offset, integer(load[2]), second_offset, copy_offset, call[1], integer(argument[1])))
    return shapes


def variants(source, name, rows, *, header=''):
    shapes = _witnesses(rows)
    visible = _visible(source, name, header) if shapes else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\bf32\s*;', context):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    prefix = part.clean[:part.opening]
    snapshot = fresh(source, header, 'repair_field_snapshot')
    proposals = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        fields = [_record_field(m[key], prefix, 'float') for key in ('first', 'field', 'second', 'out')]
        if not all(fields):
            continue
        first, load, second, copy = fields
        if not first[0] == second[0] == copy[0] == m['first_arg'] or load[0] == first[0]:
            continue
        if tuple(field[1] for field in fields) + (m['call'], integer(m['argument'])) not in shapes:
            continue
        if macros & set(re.findall(IDENT, m[0])) or re.search(r'/[*/]|#', source[m.start():m.end()]):
            continue
        prior = part.clean[part.opening + 1:m.start()].rstrip()
        if prior and prior[-1] not in ';{}:':
            continue
        pad = m['pad']
        capture = f'{pad}{{ {m["type"]} {snapshot} = {m["read"]};\n'
        proposals.append((FAMILY, edit(source, [
            (m.start('pad'), m.start('pad'), capture),
            (*m.span('read'), snapshot),
            (m.start('call'), m.start('call'), '}\n' + pad),
        ])))
        if len(proposals) == 4:
            break
    return proposals

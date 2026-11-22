"""Stage a widened field update across byte stores when the target orders it that way."""

import re

from .clamp_return_local import _field
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _visible

FAMILY = 'wide_update_before_flags'
_FPR = r'\$f(?:[12]?[0-9]|3[01])'
_FIELD = r'\*[^;={}\n]+?'
_LOAD = re.compile(rf'lwc1 ({_FPR}), ({NUMBER})\((\$\w+)\)')
_WIDE_LOAD = re.compile(rf'ldc1 ({_FPR}), %lo\(({IDENT})\)\(\$at\)')
_BYTE_STORE = re.compile(rf'sb (\$\w+), ({NUMBER})\((\$\w+)\)')
_BYTE_CAST = r'(?:s8|u8|signed\s+char|unsigned\s+char)'
_BYTE_FIELD = (
    rf'\*\s*\(\s*\(\s*{_BYTE_CAST}\s*\*\s*\)\s*'
    rf'\(\s*\(\s*\(\s*char\s*\*\s*\)\s*{IDENT}\s*\)\s*\+\s*{NUMBER}\s*\)\s*\)'
)
_SOURCE = re.compile(
    rf'(?m)^(?P<pad>[ \t]*)(?P<first>{_BYTE_FIELD})\s*=\s*0[uU]?\s*;\s*'
    rf'(?P<second>{_BYTE_FIELD})\s*=\s*1[uU]?\s*;\n'
    rf'(?P<outputpad>[ \t]*)(?P<out>{_FIELD})\s*=\s*\((?:f32|float)\)\s*(?P<narrow_expr>\(\s*'
    rf'(?P<wide_expr>\(\((?P<wide>f64|double)\)\s*\((?P<read>{_FIELD})\)\s*\)\s*\+\s*(?P<symbol>{IDENT}))\s*\))\s*;'
)


def _witnesses(rows):
    targets = [(index, left) for index, (_, left, _) in enumerate(rows) if left]
    witnessed = set()
    for i in range(len(targets) - 8):
        index, op = targets[i]
        load = _LOAD.fullmatch(op)
        wide = _WIDE_LOAD.fullmatch(targets[i + 2][1])
        first = _BYTE_STORE.fullmatch(targets[i + 5][1])
        second = _BYTE_STORE.fullmatch(targets[i + 6][1])
        if not (load and wide and first and second):
            continue
        reg, field, base = load.groups()
        wide_reg, symbol = wide.groups()
        if first[1] != '$zero' or second[1] == '$zero' or first[3] != base or second[3] != base:
            continue
        field_offset, first_offset, second_offset = map(integer, (field, first[2], second[2]))
        if first_offset == second_offset or any(field_offset <= off < field_offset + 4
                                                for off in (first_offset, second_offset)):
            continue
        group = [left for _, left in targets[i:i + 9]]
        if (group[1] != f'lui $at, %hi({symbol})' or group[3:5] != [
                f'cvt.d.s {reg}, {reg}', f'add.d {reg}, {reg}, {wide_reg}']
                or group[7:] != [f'cvt.s.d {reg}, {reg}', f'swc1 {reg}, {field}({base})']):
            continue
        if not any(left == f'addiu {second[1]}, $zero, 1' for _, left in targets[max(0, i - 4):i]):
            continue
        end = targets[i + 8][0]
        candidate = [right for _, _, right in rows[index:end + 1] if right]
        if candidate == group[:1] + group[5:7] + group[1:5] + group[7:]:
            witnessed.add((field_offset, first_offset, second_offset, symbol))
    return witnessed


def _record_field(expression, prefix, spellings):
    canonical = re.sub(rf'\(\s*{spellings}\s*\*', '(f32 *', expression, count=1)
    return _field(canonical, prefix)


def variants(source, name, rows, *, header=''):
    witnesses = _witnesses(rows)
    visible = _visible(source, name, header) if witnesses else None
    if not visible:
        return []
    part, context = visible
    if re.search(r'\btypedef\b[^;\n]*\b(?:volatile|_Atomic)\b[^;\n]*\b(?:f32|f64|s8|u8)\s*;', context):
        return []
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    prefix = part.clean[:part.opening]
    temporary = fresh(source, header, 'repair_wide_update')
    proposals = []
    for m in _SOURCE.finditer(part.clean, part.opening + 1, part.end):
        field = _record_field(m['read'], prefix, 'float')
        first = _record_field(m['first'], prefix, _BYTE_CAST)
        second = _record_field(m['second'], prefix, _BYTE_CAST)
        symbol = m['symbol']
        if not (field and first and second and field == _record_field(m['out'], prefix, 'float')
                and field[0] == first[0] == second[0] and m['pad'] == m['outputpad']):
            continue
        if (field[1], first[1], second[1], symbol) not in witnesses:
            continue
        if (not re.search(rf'\b(?:extern\s+)(?:const\s+)?{m["wide"]}\s+{symbol}\s*;', context)
                or re.search(rf'\b(?:volatile|_Atomic)\b[^;\n]*\b{symbol}\b', context)):
            continue
        if macros & set(re.findall(IDENT, m[0])) or re.search(r'/[*/]|#', source[m.start():m.end()]):
            continue
        preceding = part.clean[part.opening + 1:m.start()].rstrip()
        if preceding and preceding[-1] not in ';{}:':
            continue
        pad = m['pad']
        # Keep both byte stores and the final narrow store in their source order.
        stage = f'{pad}{{ {m["wide"]} {temporary} = {m["wide_expr"]};\n'
        proposals.append((FAMILY, edit(source, [
            (m.start(), m.start(), stage),
            (*m.span('narrow_expr'), temporary),
            (m.end(), m.end(), f'\n{pad}}}'),
        ])))
        if len(proposals) == 4:
            break
    return proposals

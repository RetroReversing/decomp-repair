"""Recover the four read and advance operations of a KMC byte cursor."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .measured_stack_drafts import _lines

REG = r'\$\w+'
VALUE = rf'(?:{NUMBER})?'
PREFIX = '__repair_cursor_byte'
RESERVED = {'$a0', '$zero', '$sp', '$ra'}
LOAD = re.compile(rf'lw (?P<cursor>{REG}), (?P<field>{VALUE})\(\$a0\)')
STEP = re.compile(
    rf'addiu (?P<next>{REG}), (?P<cursor>{REG}), (?P<advance>{NUMBER})\n'
    rf'sw (?P=next), (?P<field>{VALUE})\(\$a0\)\n'
    rf'lbu (?P<byte>{REG}), (?P<index>{VALUE})\((?P=cursor)\)'
)

DRAFT = re.compile(
    rf'\s*void \*(?P<cursor>{IDENT});\s*'
    rf'(?P=cursor) = M2C_FIELD\((?P<base>{IDENT}), void \*\*, (?P<field>{NUMBER})\);\s*'
    + ''.join(
        rf'M2C_FIELD\((?P=base), void \*\*, (?P<write{i}>{NUMBER})\) = '
        rf'\(void \*\) \((?P=cursor) \+ (?P<advance{i}>{NUMBER})\);\s*'
        for i in range(4)
    )
    + r'return '
    + r' \| '.join(
        rf'\(M2C_FIELD\((?P=cursor), u8 \*, (?P<index{i}>{NUMBER})\) << (?P<shift{i}>{NUMBER})\)'
        for i in range(3)
    )
    + rf' \| M2C_FIELD\((?P=cursor), u8 \*, (?P<index3>{NUMBER})\);\s*'
)


def _field(asm):
    if 'lbu' not in asm or 'sll' not in asm:
        return None
    lines = [' '.join(line.split()) for line in _lines(asm)
             if not line.startswith(('glabel ', 'endlabel '))]
    if len(lines) != 20 or not (load := LOAD.fullmatch(lines[0])) or load['cursor'] in RESERVED:
        return None
    field = integer(load['field'] or '0')
    if field > 0x7FFF or field % 4:
        return None
    values = []
    for i in range(4):
        step = STEP.fullmatch('\n'.join(lines[1 + i * 3:4 + i * 3]))
        if (not step or step['cursor'] != load['cursor'] or integer(step['field'] or '0') != field
                or integer(step['advance']) != i + 1 or integer(step['index'] or '0') != i
                or {step['next'], step['byte']} & (RESERVED | {load['cursor'], *values})):
            return None
        values.append(step['byte'])
    first, second, third, last = map(re.escape, values)
    if values[0] != '$v0' or not re.fullmatch(
        rf'sll {first}, {first}, (?:24|0x18)\nsll {second}, {second}, (?:16|0x10)\n'
        rf'or {first}, {first}, {second}\nsll {third}, {third}, (?:8|0x8)\n'
        rf'or {first}, {first}, {third}\njr \$ra\nor {first}, {first}, {last}',
        '\n'.join(lines[13:])
    ):
        return None
    return field


def applies(asm):
    return _field(asm) is not None


def rewrite(source, name, asm, header=''):
    """Give each byte the original cursor advance and preserve big-endian packing."""
    if 'M2C_FIELD' not in source or PREFIX in source + header or (field := _field(asm)) is None:
        return None
    part = view(source, name)
    if not part:
        return None
    signature = re.search(rf'\bs32\s+{re.escape(name)}\(void \*(?P<base>{IDENT})\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    draft = DRAFT.fullmatch(' '.join(part.clean[start:end].split()))
    if not draft or draft['base'] != signature['base'] or integer(draft['field']) != field:
        return None
    for i in range(4):
        if (integer(draft[f'write{i}']) != field or integer(draft[f'advance{i}']) != i + 1
                or integer(draft[f'index{i}']) != i or (i < 3 and integer(draft[f'shift{i}']) != 24 - i * 8)):
            return None
    values = [f'{PREFIX}{i}' for i in range(4)]
    reads = ''.join(f'    {value} = *(M2C_FIELD({draft["base"]}, u8 **, {draft["field"]}))++;\n'
                    for value in values)
    a, b, c, d = values
    return edit(source, [(start, end, (
        f'\n    u8 {a}, {b};\n    u8 {c}, {d};\n\n{reads}'
        f'    return ((u32){a} << 24) | ({b} << 16) | ({c} << 8) | {d};\n'
    ))])

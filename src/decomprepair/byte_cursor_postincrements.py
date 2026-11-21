"""Recover the four read and advance operations of a KMC byte cursor."""

import re

from . import mips_return_paths
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
    if 'M2C_FIELD' not in source or PREFIX in source + header:
        return None
    if (field := _field(asm)) is None:
        return _variable_word(source, name, asm, header)
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


_VARIABLE_WORD = re.compile(
    r'lbu \$v1, (?:0)?\(\$a1\)\nandi \$v0, \$v1, 255\nsltiu \$v0, \$v0, 128\nbeqz \$v0, \S+\n'
    r'addiu \$a1, \$a1, 1\nj \S+\nsh \$v1, (?P<slot>\d+)\(\$a0\)\n'
    r'andi \$v0, \$v1, 127\nsll \$v0, \$v0, 8\nsh \$v0, (?P=slot)\(\$a0\)\n'
    r'lbu \$v1, (?:0)?\(\$a1\)\naddiu \$a1, \$a1, 1\naddu \$v0, \$v0, \$v1\n'
    r'sh \$v0, (?P=slot)\(\$a0\)\njr \$ra\n(?:addu \$v0, \$a1, \$zero|move \$v0, \$a1)'
)
_VARIABLE_BODY = re.compile(rf'''
    \s*(?P<width>s16|s32)\s+(?P<high>{IDENT});\s*u8\s+(?P<byte>{IDENT});\s*void\s*\*\s*(?P<next>{IDENT});
    \s*(?P=byte)\s*=\s*M2C_FIELD\((?P<input>{IDENT}),\s*u8\s*\*,\s*0\);
    \s*(?P=next)\s*=\s*\(void\s*\*\)\((?P=input)\);
    \s*(?P=next)\s*=\s*\(void\s*\*\)\(\(char\s*\*\)(?P=next)\s*\+\s*\(s32\)\(1\)\);
    \s*if\s*\(\(u32\)\s*\((?P=byte)\s*&\s*0x[fF][fF]\)\s*<\s*0x80U\)\s*{{
    \s*M2C_FIELD\((?P<out>{IDENT}),\s*s16\s*\*,\s*(?P<slot>{NUMBER})\)\s*=\s*\(s16\)\s*(?P=byte);
    \s*}}\s*else\s*{{
    \s*(?P=high)\s*=\s*\((?P=byte)\s*&\s*0x7[fF]\)\s*<<\s*8;
    \s*M2C_FIELD\((?P=out),\s*s16\s*\*,\s*(?P=slot)\)\s*=\s*(?P=high);
    \s*(?P=next)\s*\+=\s*1;
    \s*M2C_FIELD\((?P=out),\s*s16\s*\*,\s*(?P=slot)\)\s*=\s*\(s16\)\s*
    \((?P=high)\s*\+\s*M2C_FIELD\((?P=input),\s*u8\s*\*,\s*1\)\);
    \s*}}\s*return\s+(?P=next);\s*
''', re.X)


def _variable_word(source, name, asm, header):
    if '0x80U' not in source or not asm or re.search(rf'\b{re.escape(name)}\s*\(', header):
        return None
    graph = mips_return_paths.graph(asm)
    if not graph or graph[1] != {3: 7, 5: 14}:
        return None
    text = '\n'.join(' '.join(row.split()) for row in graph[0])
    target = _VARIABLE_WORD.fullmatch(re.sub(r'(?<!\w)0x[\da-fA-F]+\b', lambda m: str(int(m[0], 16)), text))
    part = view(source, name) if target else None
    if not part:
        return None
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    draft = _VARIABLE_BODY.fullmatch(part.clean[start:end])
    if not draft or integer(draft['slot']) != int(target['slot']):
        return None
    cursor, output, high, first, low = (draft[k] for k in ('input', 'out', 'high', 'byte', 'next'))
    if len({cursor, output, high, first, low}) != 5:
        return None
    signature = re.search(rf'\bvoid\s*\*\s*{re.escape(name)}\(\s*void\s*\*\s*{output}\s*,'
                          rf'\s*(?P<type>void\s*\*)\s*{cursor}\s*\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    field = f'M2C_FIELD({output}, s16 *, {draft["slot"]})'
    body = f"""
    {draft['width']} {high};
    u8 {first};
    s32 {low};
    {first} = *{cursor}++;
    if ((u32) ({first} & 0xFF) < 0x80U) {{
        {field} = (s16) {first};
    }} else {{
        {high} = ({first} & 0x7F) << 8;
        {field} = {high};
        {low} = *{cursor}++;
        {field} = (s16) ({high} + {low});
    }}
    return {cursor};
"""
    return edit(source, [(*signature.span('type'), 'u8 *'), (start, end, body)])

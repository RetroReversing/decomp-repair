"""Recover a variable-byte table index and an observed forwarded argument."""

import re

from . import passthrough_argument_repairs
from .integer_repair_support import IDENT, NUMBER, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILIES = ('measured_varbyte_lookup', 'forwarded_varbyte_lookup')

_BODY = re.compile(
    rf'\s*u8\s+(?P<index>{IDENT})\s*;\s*void\s*\*\s*(?P<cursor>{IDENT})\s*;\s*'
    rf'(?P=cursor)\s*=\s*\(\s*void\s*\*\s*\)\s*\(\s*(?P<src>{IDENT})\s*\)\s*;\s*'
    rf'(?P=cursor)\s*=\s*\(\s*void\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*(?P=cursor)\s*\+\s*\(\s*s32\s*\)\s*\(\s*1\s*\)\s*\)\s*;\s*'
    rf'(?P=index)\s*=\s*M2C_FIELD\(\s*(?P=src)\s*,\s*u8\s*\*\s*,\s*0\s*\)\s*;\s*'
    rf'if\s*\(\s*(?P=index)\s*&\s*0[xX]80\s*\)\s*\{{\s*'
    rf'(?P=index)\s*=\s*\(\s*\(\s*(?P=index)\s*&\s*0[xX]7[fF]\s*\)\s*<<\s*8\s*\)\s*\|\s*'
    rf'M2C_FIELD\(\s*(?P=src)\s*,\s*u8\s*\*\s*,\s*1\s*\)\s*;\s*'
    rf'(?P=cursor)\s*\+=\s*1\s*;\s*\}}\s*'
    rf'(?P<call>{IDENT})\s*\(\s*(?P<lookup>M2C_FIELD\(\s*M2C_FIELD\(\s*(?P<dst>{IDENT})\s*,\s*void\s*\*\*\s*,\s*{NUMBER}\s*\)\s*,\s*s32\s*\*\s*,\s*{NUMBER}\s*\)\s*\+\s*\(\s*(?P=index)\s*\*\s*{NUMBER}\s*\))\s*\)\s*;\s*'
    rf'return\s+(?P=cursor)\s*;\s*')


def variants(source, name, header, rows, asm):
    part = view(source, name)
    context = source + '\n' + header
    if (not part or re.search(r'\b(?:volatile|asm|__asm__|goto|setjmp|longjmp)\b', part.clean)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:u8|u32|s32)\s*;', header)):
        return []
    end = close(part.clean, part.opening, '{', '}')
    hit = _BODY.fullmatch(part.clean[part.opening + 1:end - 1]) if end else None
    if not hit:
        return []
    index, cursor, src, dst, call = (hit[k] for k in ('index', 'cursor', 'src', 'dst', 'call'))
    if len({index, cursor, src, dst, call}) != 5:
        return []
    signature = part.clean[part.clean.rfind(name, 0, part.opening):part.opening]
    if (not re.search(rf'\bvoid\s*\*\s*{re.escape(dst)}\s*,\s*void\s*\*\s*{re.escape(src)}\s*\)', signature)
            or re.search(r'/[*/]|#', source[part.opening + 1:end - 1])):
        return []
    macros = re.findall(r'(?m)^\s*#\s*define[^\n]*', context)
    if any(re.search(rf'\b{re.escape(n)}\b', line) for n in (index, cursor, src, dst, call) for line in macros):
        return []
    definitions = re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b[^\n]*', context)
    if len(definitions) != 1 or not re.fullmatch(
            r'\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
            r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)\s*', definitions[0]):
        return []
    target = list(normalized_integer_lines(a for _, a, _ in rows if a))
    prior = list(normalized_integer_lines(b for _, _, b in rows if b))
    required = ('lbu $v1, ($s0)', 'andi $v1, $v1, 127', 'lbu $v0, ($s0)',
                'sll $v1, $v1, 8', 'or $v1, $v1, $v0', f'jal {call}')
    if (not all(line in target for line in required) or 'lbu $v1, ($a1)' not in prior
            or not target.index(required[1]) < target.index(required[2]) < target.index(required[3]) < target.index(required[4])):
        return []
    lookup = source[part.opening + 1 + hit.start('lookup'):part.opening + 1 + hit.end('lookup')]
    body = (f'\n    u32 {index};\n    u8 *{cursor};\n\n    {cursor} = {src};\n'
            f'    {index} = *{cursor};\n    {cursor} += 1;\n    if ({index} & 0x80) {{\n'
            f'        {index} &= 0x7F;\n        {index} <<= 8;\n        {index} |= *{cursor};\n'
            f'        {cursor} += 1;\n    }}\n    {call}({lookup});\n    return {cursor};\n')
    moved = edit(source, [(part.opening + 1, end - 1, body)])
    result = [(FAMILIES[0], moved)]
    forwarded = passthrough_argument_repairs.variants(moved, name, asm=asm, arch='mips', header=header,
                                                      require_evidence=True, selected_call=call, selected_slot=0)
    result.extend((FAMILIES[1], candidate) for _, candidate in forwarded)
    return result

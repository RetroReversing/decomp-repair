"""Recover a measured big-endian halfword read with an advancing byte cursor."""

import re

from .csource import _blank, find
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_be16_cursor'

_BODY = re.compile(
    rf'\s*M2C_FIELD\(\s*(?P<obj>{IDENT})\s*,\s*s16\s*\*\s*,\s*(?P<slot>{NUMBER})\s*\)\s*=\s*'
    rf'\(\s*s16\s*\)\s*\(\s*M2C_FIELD\(\s*(?P<src>{IDENT})\s*,\s*u8\s*\*\s*,\s*1\s*\)\s*\|\s*'
    rf'\(\s*M2C_FIELD\(\s*(?P=src)\s*,\s*u8\s*\*\s*,\s*0\s*\)\s*<<\s*8\s*\)\s*\)\s*;\s*'
    rf'M2C_FIELD\(\s*(?P=obj)\s*,\s*s16\s*\*\s*,\s*(?P<clear>{NUMBER})\s*\)\s*=\s*0\s*;\s*'
    rf'return\s+(?P=src)\s*\+\s*1\s*\+\s*1\s*;\s*')


def variants(source, name, header, rows):
    part = view(source, name)
    context = source + '\n' + header
    if (not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s16|u8|u32)\s*;', header)
            or '__repair_be16_' in context):
        return []
    end = close(part.clean, part.opening, '{', '}')
    hit = _BODY.fullmatch(part.clean[part.opening + 1:end - 1]) if end else None
    if not hit or hit['obj'] == hit['src'] or abs(integer(hit['slot']) - integer(hit['clear'])) < 2:
        return []
    span = find(source, name)
    if not span:
        return []
    signature = re.search(rf'\bvoid\s*\*\s*{re.escape(name)}\s*\(\s*void\s*\*\s*{re.escape(hit["obj"])}\s*,\s*'
                          rf'(?P<src_type>void)\s*\*\s*{re.escape(hit["src"])}\s*\)\s*$', part.clean[:part.opening])
    if not signature or re.search(rf'\b{re.escape(name)}\s*\(', _blank(header) + part.clean[:span[0]] + part.clean[span[1]:]):
        return []
    macros = re.findall(r'(?m)^\s*#\s*define[^\n]*', context)
    if any(re.search(rf'\b{re.escape(n)}\b', line) for n in (hit['obj'], hit['src']) for line in macros):
        return []
    definitions = re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+M2C_FIELD\b[^\n]*', context)
    if (len(definitions) != 1 or not re.fullmatch(
            r'\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s*'
            r'\(\*\(type_ptr\)\(\(s8\s*\*\)\(expr\)\s*\+\s*\(offset\)\)\)\s*', definitions[0])
            or re.search(r'/[*/]|#', source[part.opening + 1:end - 1])):
        return []
    target = list(normalized_integer_lines(a for _, a, _ in rows if a))
    prior = list(normalized_integer_lines(b for _, _, b in rows if b))
    expected = ['lbu $v1, ($a1)', 'addiu $a1, $a1, 1', 'lbu $v0, ($a1)',
                f'sh $zero, {integer(hit["clear"])}($a0)', 'sll $v1, $v1, 8', 'or $v0, $v0, $v1',
                f'sh $v0, {integer(hit["slot"])}($a0)', 'jr $ra', 'addiu $v0, $a1, 1']
    if target != expected or prior[:2] != ['lbu $v1, 1($a1)', 'lbu $v0, ($a1)']:
        return []
    body = (f'\n    u32 __repair_be16_hi = *{hit["src"]}++;\n    u32 __repair_be16_lo = *{hit["src"]};\n'
            f'    M2C_FIELD({hit["obj"]}, s16 *, {hit["slot"]}) = (s16) (__repair_be16_lo | (__repair_be16_hi << 8));\n'
            f'    M2C_FIELD({hit["obj"]}, s16 *, {hit["clear"]}) = 0;\n    return {hit["src"]} + 1;\n')
    return [(FAMILY, edit(source, [(*signature.span('src_type'), 'u8'), (part.opening + 1, end - 1, body)]))]

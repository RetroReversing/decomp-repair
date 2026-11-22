"""Repair a byte-indexed inferred global and its clamp's return guard."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, locals_for, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_byte_clamp'


def variants(source, name, header, rows):
    part = view(source, name)
    if (not part or re.search(r'\b(?:volatile|asm|__asm__|goto|setjmp|longjmp)\b', part.clean)
            or re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s8|u8|s32|u32|M2C_UNK)\s*;', header)):
        return []
    diff = [normalized_integer_lines((a, b)) for _, a, b in rows]
    # A halfword index goes directly into the target's byte load, but the
    # candidate scales that index as a four-byte inferred global.
    if (not any(re.fullmatch(r'sll (\$\w+), \1, 2', b) and not a for a, b in diff)
            or not any(a.startswith('lhu ') and a == b for a, b in diff)
            or not any(a.startswith('lbu ') and b.startswith('lbu ') for a, b in diff)):
        return []
    decls = {d['name']: d['type'] for d in locals_for(part)}
    tail = re.compile(
        rf'(?P<result>{IDENT})\s*=\s*0\s*;\s*if\s*\(\s*(?P<value>{IDENT})\s*>=\s*(?P<minimum>{NUMBER})\s*\)\s*\{{'
        rf'(?P<body>.*?)\b(?P=result)\s*=\s*(?P<out>{IDENT})\s*&\s*(?P<mask>0[xX][fF][fF]|255)[uU]?\s*;\s*\}}\s*'
        rf'return\s+(?P=result)\s*;\s*\}}', re.S)
    match = tail.search(part.clean, part.opening + 1, part.end)
    if not match:
        return []
    prefix = part.clean[part.opening + 1:match.start()].rstrip()
    if (not prefix or prefix[-1] not in ';}' or prefix.count('{') != prefix.count('}')
            or match.end() != close(part.clean, part.opening, '{', '}')):
        return []
    result, value, out = (match[k] for k in ('result', 'value', 'out'))
    if (decls.get(result) not in ('s32', 'int') or decls.get(value) not in ('u32', 'unsigned int')
            or decls.get(out) != 'u8' or len({result, value, out}) != 3
            or len(re.findall(rf'\b{re.escape(result)}\b', part.body)) != 4
            or re.search(r'\b(?:return|break|continue)\b', match['body'])):
        return []
    if not re.search(rf'\b{re.escape(value)}\s*=\s*{re.escape(out)}\s*&\s*(?:0[xX][fF][fF]|255)[uU]?\s*;',
                     part.clean[part.opening:match.start()]):
        return []
    # The only proposed address change is the generated unknown global plus a
    # literal byte displacement and an index loaded through a halfword field.
    address = re.compile(
        rf'&(?P<base>{IDENT})\s*\+\s*(?P<offset>{NUMBER})\s*\+\s*'
        rf'M2C_FIELD\(\s*M2C_FIELD\(\s*&{IDENT}\s*,\s*void\s*\*\*\s*,\s*{NUMBER}\s*\)\s*,\s*u16\s*\*\s*,\s*{NUMBER}\s*\)')
    hits = list(address.finditer(part.clean, match.start('body'), match.end('body')))
    if len(hits) != 1:
        return []
    hit = hits[0]
    base = hit['base']
    if (not re.search(rf'\bextern\s+M2C_UNK\s+{re.escape(base)}\s*;', part.clean[:part.opening])
            or re.search(rf'\b{re.escape(base)}\b', _blank(header))
            or re.search(r'/[*/]|#', source[match.start():match.end()])):
        return []
    macros = re.findall(r'(?m)^\s*#\s*define[^\n]*', source + '\n' + header)
    if any(re.search(rf'\b(?:{re.escape(result)}|{re.escape(value)}|{re.escape(out)}|{re.escape(base)})\b', line)
           for line in macros):
        return []
    body = source[match.start('body'):match.end('body')]
    relative = hit.start() - match.start('body')
    body = body[:relative] + '(s8 *)' + body[relative:]
    replacement = (f'if ({value} < {match["minimum"]}) {{ return 0; }}\n    {{'
                   + body + f'return {out} & {match["mask"]};\n    }}\n}}')
    return [(FAMILY, edit(source, [(match.start(), match.end(), replacement)]))]

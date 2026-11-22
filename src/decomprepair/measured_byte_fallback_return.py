"""Recover byte-sized range normalization with a direct fallback return."""

import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
LITERAL = rf'{NUM}[uUlL]*'
TARGET = re.compile(
    rf'addiu \$v0, \$a0, -(?P<base>{NUM})\nandi \$v0, \$v0, 0xff\n'
    rf'sltiu \$v0, \$v0, (?P<limit>{NUM})\nbeqz \$v0, [^\n]+\nmove \$v1, \$a0\n'
    rf'addiu \$v0, \$a0, (?P<delta>{NUM})\n[^\n]+\nandi \$v0, \$v0, 0xff\n'
    rf'andi \$a0, \$v1, 0xff\naddiu \$v1, \$zero, (?P<key>{NUM})\n'
    rf'beq \$a0, \$v1, [^\n]+\naddiu \$v0, \$zero, (?P<replacement>{NUM})\nmove \$v0, \$a0'
)
CANDIDATE = re.compile(
    rf'addiu \$v0, \$a0, -(?P<base>{NUM})\nandi \$v0, \$v0, 0xff\n'
    rf'sltiu \$v0, \$v0, (?P<limit>{NUM})\nbeqz \$v0, [^\n]+\n'
    rf'addiu \$v0, \$a0, (?P<delta>{NUM})\n'
)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c = TARGET.search(target), CANDIDATE.search(candidate)
    if not t or not c or any(int(t[k], 0) != int(c[k], 0) for k in ('base', 'limit', 'delta')):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.clean):
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    part.end = end
    signature = re.search(rf'\bs32\s+{re.escape(name)}\s*\(\s*s32\s+(?P<arg>{IDENT})\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature:
        return []
    arg = signature['arg']
    body = re.compile(
        rf'\s*s32\s+(?P<tmp>{IDENT})\s*;\s*s32\s+(?P<result>{IDENT})\s*;\s*'
        rf'if\s*\(\s*\(u32\)\s*\(\s*\(\s*{re.escape(arg)}\s*-\s*(?P<base>{LITERAL})\s*\)\s*&\s*0[xX]FF\s*\)\s*'
        rf'<\s*(?P<limit>{LITERAL})\s*\)\s*{{\s*return\s*\(\s*{re.escape(arg)}\s*\+\s*(?P<delta>{LITERAL})\s*\)\s*&\s*0[xX]FF\s*;\s*}}\s*'
        rf'(?P=tmp)\s*=\s*{re.escape(arg)}\s*&\s*0[xX]FF\s*;\s*(?P=result)\s*=\s*(?P<replacement>{LITERAL})\s*;\s*'
        rf'if\s*\(\s*(?P=tmp)\s*!=\s*(?P<key>{LITERAL})\s*\)\s*{{\s*(?P=result)\s*=\s*(?P=tmp)\s*;\s*}}\s*'
        rf'return\s+(?P=result)\s*;\s*'
    )
    m = body.fullmatch(part.body)
    if not m or len({arg, m['tmp'], m['result']}) != 3:
        return []
    if any(int(m[k].rstrip('uUlL'), 0) != int(t[k], 0) for k in ('base', 'limit', 'delta', 'key', 'replacement')):
        return []
    if any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(x)}\b', source + '\n' + header)
           for x in (arg, m['tmp'], m['result'])):
        return []
    original = source[part.opening + 1:part.end - 1]
    if '/*' in original or '//' in original or '#' in original:
        return []
    replacement = (f'\n    u8 {m["tmp"]};\n\n'
                   f'    if ((u8) ({arg} - {m["base"]}) < {m["limit"]}) {{\n'
                   f'        return (u8) ({arg} + {m["delta"]});\n    }}\n'
                   f'    {m["tmp"]} = {arg};\n'
                   f'    if ({m["tmp"]} == {m["key"]}) {{\n        return {m["replacement"]};\n    }}\n'
                   f'    return {m["tmp"]};\n')
    return [('measured_byte_fallback_return', edit(source, [(part.opening + 1, part.end - 1, replacement)]))]

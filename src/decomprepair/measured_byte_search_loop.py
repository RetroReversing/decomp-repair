"""Recover a measured zero-terminated byte search with a byte-sized key."""

import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

TARGET = re.compile(
    r'lbu \$v1, \(\$a0\)\nandi \$a1, \$a1, 0xff\nandi \$v0, \$v1, 0xff\n'
    r'beq \$v0, \$a1, [^\n]+\nmove \$v0, \$a0\nbnez \$v1, [^\n]+\n'
    r'addiu \$a0, \$a0, 1\nj [^\n]+\nmove \$v0, \$zero\n'
    r'lbu \$v1, \(\$a0\)\nbne \$v1, \$a1, [^\n]+\nmove \$v0, \$a0'
)
CANDIDATE = re.compile(
    r'move \$v0, \$a0\nlbu \$a0, \(\$v0\)\nandi \$a1, \$a1, 0xff\n'
    r'beq \$a0, \$a1, [^\n]+\nmove \$v1, \$v0'
)


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    if not TARGET.search(target) or not CANDIDATE.search(candidate):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    part.end = end
    signature = re.search(rf'\bu8\s*\*\s*{re.escape(name)}\s*\(\s*u8\s*\*\s*(?P<str>{IDENT})\s*,\s*'
                          rf's32\s+(?P<key>{IDENT})\s*\)', part.clean[:part.opening])
    if not signature:
        return []
    pattern = re.compile(
        rf'\s*s32\s+(?P<needle>{IDENT})\s*;\s*u8\s*\*\s*(?P<cursor>{IDENT})\s*;\s*'
        rf'u8\s*\*\s*(?P<result>{IDENT})\s*;\s*u8\s+(?P<byte>{IDENT})\s*;\s*'
        rf'(?P=cursor)\s*=\s*{re.escape(signature["str"])}\s*;\s*'
        rf'(?P=byte)\s*=\s*\*\s*(?P=cursor)\s*;\s*'
        rf'(?P=needle)\s*=\s*{re.escape(signature["key"])}\s*&\s*0[xX][fF][fF]\s*;\s*'
        rf'(?P=result)\s*=\s*(?P=cursor)\s*;\s*'
        rf'if\s*\(\s*\(\s*(?P=byte)\s*&\s*0[xX][fF][fF]\s*\)\s*!=\s*(?P=needle)\s*\)\s*{{\s*'
        rf'(?P<label>{IDENT})\s*:\s*(?P=cursor)\s*\+=\s*1\s*;\s*'
        rf'if\s*\(\s*(?P=byte)\s*==\s*0\s*\)\s*{{\s*return\s+NULL\s*;\s*}}\s*'
        rf'(?P=byte)\s*=\s*\*\s*(?P=cursor)\s*;\s*(?P=result)\s*=\s*(?P=cursor)\s*;\s*'
        rf'if\s*\(\s*(?P=byte)\s*==\s*(?P=needle)\s*\)\s*{{\s*return\s+(?P=result)\s*;\s*}}\s*'
        rf'goto\s+(?P=label)\s*;\s*}}\s*return\s+(?P=result)\s*;\s*'
    )
    m = pattern.fullmatch(part.body)
    if not m or len({signature['str'], signature['key'], m['needle'], m['cursor'], m['result'], m['byte']}) != 6:
        return []
    if any(re.search(rf'(?m)^\s*#\s*define\s+{re.escape(x)}\b', source + '\n' + header)
           for x in (signature['str'], signature['key'], m['needle'], m['cursor'], m['result'], m['byte'])):
        return []
    original = source[part.opening + 1:part.end - 1]
    # m2c emits this duplicate-return note; do not discard handwritten comments.
    original = re.sub(r'/\*\s*Duplicate return node #[0-9]+\. Try simplifying control flow for better match\s*\*/',
                      '', original)
    if '/*' in original or '//' in original or '#' in original:
        return []
    cursor, byte, needle = m['cursor'], m['byte'], m['needle']
    replacement = (f'\n    u8 {needle};\n    u8 *{cursor};\n    u8 {byte};\n\n'
                   f'    {cursor} = {signature["str"]};\n    {byte} = *{cursor};\n'
                   f'    {needle} = {signature["key"]} & 0xFF;\n'
                   f'    if ({byte} != {needle}) {{\n        do {{\n'
                   f'            if ({byte} == 0) {{\n                return NULL;\n            }}\n'
                   f'            {cursor} += 1;\n            {byte} = *{cursor};\n'
                   f'        }} while ({byte} != {needle});\n    }}\n    return {cursor};\n')
    return [('measured_byte_search_loop', edit(source, [(part.opening + 1, part.end - 1, replacement)]))]

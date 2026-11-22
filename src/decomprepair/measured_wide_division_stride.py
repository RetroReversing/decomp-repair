"""Recover a byte-stride indexed 64-bit division in measured KMC output."""

import re

from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
LOAD = re.compile(rf'lw \$v0, \(\$v1\)\nsll \$v0, \$v0, (?P<shift>[0-9]+)\n'
                  rf'addu \$v1, \$v1, \$v0\nlw \$a0, (?P<high>{NUM})\(\$v1\)\n'
                  rf'lw \$a1, (?P<low>{NUM})\(\$v1\)')
DIV = re.compile(rf'jal __udivdi3\naddiu \$a3, \$zero, (?P<divisor>{NUM})')


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    t, c, div = LOAD.search(target), LOAD.search(candidate), DIV.search(target)
    if not t or not c or not div or t['shift'] != '3' or c['shift'] != '5':
        return []
    if (t['high'], t['low']) != (c['high'], c['low']) or int(t['high'], 0) % 8:
        return []
    if int(t['low'], 0) != int(t['high'], 0) + 4:
        return []
    if re.search(r'\b__repair_u64_word_aligned\b', header + '\n' + source):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    if re.search(r'\b__udivdi3\b', header) or len(re.findall(r'\b__udivdi3\b', part.clean)) != 2:
        return []
    declaration = re.search(r'\bu64\s+__udivdi3\s*\(\s*s32\s*,\s*s32\s*,\s*M2C_UNK\s*,\s*M2C_UNK\s*\)\s*;',
                            part.clean[:part.opening])
    if not declaration:
        return []
    pattern = re.compile(
        rf'(?P<ptr>{IDENT})\s*=\s*(?P<base>M2C_FIELD\(\s*&\s*{IDENT}\s*,\s*s32\s*\*\*\s*,\s*{NUM}\s*\))\s*'
        rf'\+\s*\(\s*\*\s*(?P=base)\s*\*\s*8\s*\)\s*;\s*'
        rf'return\s*\(u32\)\s*__udivdi3\(\s*M2C_FIELD\(\s*(?P=ptr)\s*,\s*s32\s*\*\s*,\s*'
        rf'(?P<high>{NUM})\s*\)\s*,\s*M2C_FIELD\(\s*(?P=ptr)\s*,\s*s32\s*\*\s*,\s*'
        rf'(?P<low>{NUM})\s*\)\s*,\s*0\s*,\s*(?P<divisor>{NUM})\s*\)'
    )
    hits = list(pattern.finditer(part.body))
    if len(hits) != 1:
        return []
    m = hits[0]
    if any(int(m[x], 0) != int(y, 0) for x, y in
           (('high', t['high']), ('low', t['low']), ('divisor', div['divisor']))):
        return []
    if not re.search(rf'\bvoid\s*\*\s*{re.escape(m["ptr"])}\s*;', part.body):
        return []
    if len(re.findall(rf'\b{re.escape(m["ptr"])}\b', part.body)) != 4:
        return []
    original = source[part.opening + 1 + m.start():part.opening + 1 + m.end()]
    if '/*' in original or '//' in original:
        return []
    replacement = (f'{m["ptr"]} = (char *) {m["base"]} + (*{m["base"]} * 8);\n'
                   f'    return (u32) __udivdi3(M2C_FIELD({m["ptr"]}, __repair_u64_word_aligned *, {m["high"]}), {m["divisor"]})')
    return [('measured_wide_division_stride', edit(source, [
        (declaration.start(), declaration.end(),
         'typedef u64 __attribute__((aligned(4))) __repair_u64_word_aligned;\n'
         'u64 __udivdi3(u64, u64);'),
        (part.opening + 1 + m.start(), part.opening + 1 + m.end(), replacement),
    ]))]

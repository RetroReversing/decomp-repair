"""Recover a measured slot flip followed by an indexed pointer copy."""

import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

NUM = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
TARGET = re.compile(
    rf'lui \$a0, %hi\((?P<symbol>{IDENT})\)\naddiu \$a0, \$a0, %lo\((?P=symbol)\)\n'
    rf'lw \$v1, \(\$a0\)\naddiu \$v0, \$zero, 1\nsubu \$v0, \$v0, \$v1\n'
    rf'sw \$v0, \(\$a0\)\nlui \$v0, %hi\((?P=symbol)\)\nlw \$v0, %lo\((?P=symbol)\)\(\$v0\)\n'
    rf'sll \$v0, \$v0, 2\naddu \$v1, \$a0, \$v0\nlw \$v1, -(?P<src>{NUM})\(\$v1\)\n'
    rf'addiu \$a0, \$a0, -(?P<dest>{NUM})\naddu \$v0, \$v0, \$a0'
)


def variants(source, name, header, rows, *, resolve=None):
    if resolve is None:
        return []
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    evidence = TARGET.search(target)
    if not evidence or TARGET.search(candidate):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean):
        return []
    pattern = re.compile(
        rf'(?P<ptr>{IDENT})\s*=\s*\(char\s*\*\)\s*&\s*(?P<base>{IDENT})\s*\+\s*(?P<off>{NUM})\s*;\s*'
        rf'M2C_FIELD\(\s*&\s*(?P=base)\s*,\s*s32\s*\*\s*,\s*(?P=off)\s*\)\s*=\s*'
        rf'\(s32\)\s*\(\s*1\s*-\s*M2C_FIELD\(\s*&\s*(?P=base)\s*,\s*s32\s*\*\s*,\s*(?P=off)\s*\)\s*\)\s*;\s*'
        rf'(?P<index>{IDENT})\s*=\s*M2C_FIELD\(\s*&\s*(?P=base)\s*,\s*s32\s*\*\s*,\s*(?P=off)\s*\)\s*\*\s*4\s*;\s*'
        rf'(?P<addr>{IDENT})\s*=\s*\(char\s*\*\)\s*\(\s*(?P=index)\s*\+\s*\(\s*(?P=ptr)\s*-\s*(?P<dest>{NUM})\s*\)\s*\)\s*;\s*'
        rf'\*\s*\(s32\s*\*\)\s*\(\s*(?P=addr)\s*\)\s*=\s*M2C_FIELD\(\s*\(\s*(?P=ptr)\s*\+\s*(?P=index)\s*\)\s*,\s*s32\s*\*\s*,\s*-(?P<src>{NUM})\s*\)\s*;'
    )
    hits = list(pattern.finditer(part.body))
    if len(hits) != 1:
        return []
    m = hits[0]
    if int(m['src'], 0) != int(evidence['src'], 0) or int(m['dest'], 0) != int(evidence['dest'], 0):
        return []
    base, symbol = resolve(m['base']), resolve(evidence['symbol'])
    if base is None or symbol is None or base + int(m['off'], 0) != symbol:
        return []
    if re.search(rf'\b{re.escape(evidence["symbol"])}\b', source + '\n' + header):
        return []
    ptr, index, addr = m['ptr'], m['index'], m['addr']
    decl = re.search(rf'\bvoid\s*\*\s*{re.escape(ptr)}\s*;', part.body)
    if (not decl or not re.search(rf'\bs32\s+{re.escape(index)}\s*;', part.body)
            or not re.search(rf'\bchar\s*\*\s*{re.escape(addr)}\s*;', part.body)):
        return []
    if any(len(re.findall(rf'\b{re.escape(x)}\b', part.body)) != n for x, n in ((ptr, 4), (index, 4), (addr, 3))):
        return []
    old = source[part.opening + 1 + m.start():part.opening + 1 + m.end()]
    tmp = '__repair_slot_value'
    if '/*' in old or '//' in old or re.search(rf'\b{tmp}\b', source + '\n' + header):
        return []
    replacement = (f'{ptr} = (char *)&{evidence["symbol"]};\n'
                   f'    *(s32 *){ptr} = 1 - *(s32 *){ptr};\n'
                   f'    {index} = {evidence["symbol"]} * 4;\n'
                   f'    {tmp} = *(s32 *)(({ptr} - (-{index})) - {m["src"]});\n'
                   f'    {ptr} -= {m["dest"]};\n'
                   f'    *(s32 *)({ptr} + {index}) = {tmp};')
    start, _ = find(source, name)
    return [('measured_slot_flip_copy', edit(source, [
        (start, start, f'extern s32 {evidence["symbol"]};\n'),
        (part.opening + 1, part.opening + 1, f'\n    s32 {tmp};'),
        (part.opening + 1 + decl.start(), part.opening + 1 + decl.end(), f'char *{ptr};'),
        (part.opening + 1 + m.start(), part.opening + 1 + m.end(), replacement),
    ]))]

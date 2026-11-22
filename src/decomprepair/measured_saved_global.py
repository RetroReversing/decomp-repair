"""Recover a previous global pointer saved across a replacement."""

import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'measured_saved_global'
LOAD = re.compile(rf'lui \$v1, %hi\((?P<symbol>{IDENT})\)\nlw \$v1, %lo\((?P=symbol)\)\(\$v1\)')
STORE = re.compile(rf'lui \$at, %hi\((?P<symbol>{IDENT})\)\nsw \$v0, %lo\((?P=symbol)\)\(\$at\)\n'
                   rf'lui \$at, %hi\((?P<saved>{IDENT})\)\nsw \$v1, %lo\((?P=saved)\)\(\$at\)')


def variants(source, name, header, rows, *, resolve=None):
    if resolve is None:
        return []
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    candidate = '\n'.join(' '.join(right.split()) for _, _, right in rows if right)
    load, store = LOAD.search(target), STORE.search(target)
    if (not load or not store or load['symbol'] != store['symbol'] or LOAD.search(candidate)
            or not STORE.search(candidate)):
        return []
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__|goto)\b', part.clean):
        return []
    start, _ = find(source, name)
    if re.search(rf'\b{re.escape(load["symbol"])}\b', source + '\n' + header):
        return []
    pattern = re.compile(
        rf'M2C_FIELD\(\s*&\s*(?P<base>{IDENT})\s*,\s*M2C_UNK\s*\*\*\s*,\s*'
        rf'(?P<offset>0x[0-9a-fA-F]+|\d+)\s*\)\s*=\s*&\s*(?P<new>{IDENT})\s*;\s*'
        rf'(?P<saved>{IDENT})\s*=\s*(?P<temp>{IDENT})\s*;\s*'
        rf'(?P=temp)\s*=\s*M2C_FIELD\(\s*&\s*(?P=base)\s*,\s*M2C_UNK\s*\*\*\s*,\s*(?P=offset)\s*\)\s*;'
    )
    matches = list(pattern.finditer(part.body))
    if len(matches) != 1:
        return []
    m = matches[0]
    if (m['saved'] != store['saved'] or len(re.findall(rf'\b{re.escape(m["temp"])}\b', part.body)) != 3
            or not re.search(rf'\bM2C_UNK\s*\*\s*{re.escape(m["temp"])}\s*;', part.body)):
        return []
    base, symbol = resolve(m['base']), resolve(load['symbol'])
    if base is None or symbol is None or symbol != base + int(m['offset'], 0):
        return []
    if re.search(r'[/#]', part.body[m.start():m.end()]):
        return []
    replacement = (f'{m["temp"]} = {load["symbol"]};\n    {load["symbol"]} = &{m["new"]};\n'
                   f'    {m["saved"]} = {m["temp"]};')
    return [(FAMILY, edit(source, [(start, start, f'extern M2C_UNK *{load["symbol"]};\n'),
                                   (part.opening + 1 + m.start(), part.opening + 1 + m.end(), replacement)]))]

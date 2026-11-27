"""Chain consecutive float-zero field stores when the target keeps zero in a float register.

On a GCC 2.7.2 KMC function three independent zero stores used integer zero, while the target used one float zero
and three `swc1` instructions. Chaining the same stores kept their order and improved the O2 score from 48,075 to
47,535 and an O1 diagnostic from 3,410 to 2,610. This is one function, not a match.
"""
import re

from .integer_repair_support import view
from .shared_float_equality_ladder import _MACRO

FAMILY = 'float_zero_store_chain'
FAMILIES = (FAMILY,)
_FIELD = r'M2C_FIELD\(\s*(?P<base>[A-Za-z_]\w*)\s*,\s*f32\s*\*\s*,\s*(?P<offset>0[xX][0-9a-fA-F]+|\d+)\s*\)'
_STORE = re.compile(r'(?P<field>' + _FIELD + r')\s*=\s*0(?:\.0*)?[fF]\s*;')
_ASM_STORE = re.compile(r'\bswc1\s+\$(\w+)\s*,\s*(0[xX][0-9a-fA-F]+|\d+)\(\$(\w+)\)')


def variants(source, name, asm, header=''):
    part = view(source, name)
    if not part or not _MACRO.search(source + '\n' + (header or '')):
        return []
    lines = (asm or '').splitlines()
    target = []
    for i in range(len(lines) - 2):
        stores = [_ASM_STORE.search(line) for line in lines[i:i + 3]]
        if any(not x for x in stores):
            continue
        if len({(x[1], x[3]) for x in stores}) != 1:
            continue
        reg = stores[0][1]
        if not any(re.search(r'\bmtc1\s+\$zero\s*,\s*\$' + re.escape(reg) + r'\b', line)
                   for line in lines[max(0, i - 3):i]):
            continue
        target.append([int(x[2], 0) for x in stores])
    out = []
    for first in _STORE.finditer(part.clean, part.opening, part.end):
        matches = [first]
        for _ in range(2):
            at = re.match(r'\s*', part.clean[matches[-1].end():]).end() + matches[-1].end()
            nxt = _STORE.match(part.clean, at)
            if not nxt:
                break
            matches.append(nxt)
        if len(matches) != 3 or len({m['base'] for m in matches}) != 1:
            continue
        if any(source[a.end():b.start()].strip() for a, b in zip(matches, matches[1:])):
            continue  # retain comments between stores
        offsets = [int(m['offset'], 0) for m in matches]
        if len(set(offsets)) != 3 or offsets not in target:
            continue
        chain = ' = '.join(source[m.start('field'):m.end('field')] for m in reversed(matches)) + ' = 0.0f;'
        out.append((FAMILY, source[:first.start()] + chain + source[matches[-1].end():]))
    return out[:24]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}

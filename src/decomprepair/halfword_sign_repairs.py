"""m2c's `((E != 0) * -0x10000) | 0x10000`, the sign of a 16.16 value, with the sign held in an `s16` first.

A function returning plus or minus one in 16.16 fixed point comes back from m2c as a multiply of the test by
`-0x10000`, or-ed with `0x10000`. gcc 2.7.2 builds that as `-(E != 0)` masked with `0xFFFF0000`; the game shifted it,
`sltu; negu; sll 16; lui 1; or`, which is what it does when the sign is a halfword. Two twin N64 functions were stuck at
the masked form (1575 points off) and came within register choice of the game (680) with
`s16 sign = -(E != 0); ... (sign << 16) | 0x10000`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'halfword_sign'
FAMILIES = (FAMILY,)

PRODUCT = re.compile(r'\(\s*\(\s*(?P<test>\((?:[^()]|\([^()]*\))*\)|[A-Za-z_]\w*)\s*!=\s*0\s*\)\s*\*\s*-0x(?P<k>[0-9A-Fa-f]*)0000\s*\)'
                     r'\s*\|\s*0x(?P=k)0000')
NAME = '__repair_sign'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or NAME in clean:
        return []
    hit = PRODUCT.search(clean, opening, end)
    if not hit:
        return []
    if hit['k'] != '1':
        return []  # (only the 16.16 case is known; another scale would need another width)
    line = clean.rfind('\n', 0, hit.start()) + 1
    indent = re.match(r'[ \t]*', clean[line:])[0]
    test = source[hit.start('test'):hit.end('test')]
    statement = f'{indent}{NAME} = -({test} != 0);\n'
    text = (source[:line] + statement + source[line:hit.start()] + f'({NAME} << 16) | 0x10000'
            + source[hit.end():])
    text = text[:opening + 1] + f'\n    s16 {NAME};' + text[opening + 1:]
    return [(FAMILY, text)]

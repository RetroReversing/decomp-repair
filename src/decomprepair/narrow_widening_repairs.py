"""A narrow local or parameter m2c typed from one access, as the `int` the source had.

m2c types a local from the load that fills it: `s8 temp_s1 = M2C_FIELD(p, s8 *, 0xE);`. gcc 2.7.2 then reads the
field with `lbu` and sign-extends where the value is used, or keeps a halfword parameter's `sll`/`sra`; the game
read it with `lb` into an `int` and used it as it was. Two N64 functions holding a byte field across a call (86.6%,
90.0%) and one storing an `s16` parameter (70.0%) were exact with the local or parameter as `s32`. One variant per
local or parameter, each alone.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'narrow_widening'
FAMILIES = (FAMILY,)

NARROW = r'(?:s8|u8|s16|u16|signed\s+char|unsigned\s+char|short|unsigned\s+short|char)'
IDENT = r'[A-Za-z_]\w*'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    signature_at = clean.rfind('(', span[0], opening)
    found = []
    for m in re.finditer(r'(?<![\w*])(' + NARROW + r')\s+(' + IDENT + r')\s*(?=[,)])', clean[signature_at:opening]):
        found.append((signature_at + m.start(1), signature_at + m.end(1)))
    for m in re.finditer(r'(?m)^[ \t]*(?:register\s+)?(' + NARROW + r')\s+(' + IDENT + r')\s*;', clean[opening:end]):
        found.append((opening + m.start(1), opening + m.end(1)))
    result = []
    for start, stop in found[:8]:
        text = source[:start] + 's32' + source[stop:]
        if text != source:
            result.append((FAMILY, text))
    return result

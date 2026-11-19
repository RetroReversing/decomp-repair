"""`0.0f` stores written through a float zero, where the target stores the FPU's zero.

gcc 2.7.2 stores a literal `0.0f` into a float field as an integer zero (`sw $zero`); the game stored `$f0` after
`mtc1 $zero, $f0`. An N64 function clearing a vector's three components (0% so) was exact with them set from one
`f32` local (or a chained assignment). Offered only when the target has `mtc1 $zero`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'float_zero_local'
FAMILIES = (FAMILY,)


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm or not re.search(r'\bmtc1\s+\$zero\b', asm):
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    stores = list(re.finditer(r'=\s*0\.0f?\s*;', clean[opening:end]))
    if not stores or '__repair_fzero' in clean:
        return []
    text = source
    for m in reversed(stores):
        a = opening + m.start()
        text = text[:a] + '= __repair_fzero;' + text[opening + m.end():]
    text = text[:opening + 1] + '\n    f32 __repair_fzero = 0.0f;\n' + text[opening + 1:]
    return [(FAMILY, text)]

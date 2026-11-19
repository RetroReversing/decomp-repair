"""m2c's `M2C_UNK32` fields as the floats the target moves them as.

When m2c can't tell a word's type it writes `M2C_UNK32`, which gcc copies with `lw`/`sw`. The game moved such a
field through the FPU (`lwc1`, `swc1`): an N64 function saving one field into another was 73.3% with the integer copy
and exact with the field and its temporary as `f32`. Offered when the target has a float load or store at one of
the offsets the `M2C_UNK32` accesses use.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'unknown32_float'
FAMILIES = (FAMILY,)


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm or 'M2C_UNK32' not in source[span[0]:span[1]]:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    floats = {int(m[1], 0) for m in re.finditer(r'\b(?:lwc1|swc1)\s+\$\w+\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))\s*\(', asm)}
    offsets = {int(m[1], 0) for m in re.finditer(r'M2C_UNK32\s*\*\s*,\s*(0x[0-9a-fA-F]+|\d+)\s*\)', clean[opening:end])}
    if not floats & offsets:
        return []
    text = source[:opening] + re.sub(r'\bM2C_UNK32\b', 'f32', source[opening:end]) + source[end:]
    return [(FAMILY, text)] if text != source else []

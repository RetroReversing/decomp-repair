"""m2c's masks on a word parameter the game used whole.

m2c writes `(arg1 & 0xFFFF)` wherever a parameter reaches a callee it believes takes a `u16`, or a test of the low
half; when the game passed and tested the word itself, every mask costs an `andi` the target doesn't have. An N64
function was 97.3% with three such masks and exact without them. Offered per parameter, all its masks of one width
dropped together, when the target has fewer `andi` of that width than the C has masks on the parameter (the other
direction, a narrow parameter masked at each use, is `parameter_mask`).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'parameter_mask_drop'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    header = clean[span[0]:opening]
    params = re.findall(r'\b(?:s32|u32|int|unsigned int|unsigned)\s+(' + IDENT + r')\s*[,)]', header)
    result = []
    for param in params:
        for mask in ('0xFFFF', '0xFF'):
            uses = list(re.finditer(r'\(\s*' + param + r'\s*&\s*' + mask + r'\s*\)', clean[opening:end], re.I))
            if not uses:
                continue
            target = len(re.findall(r'\bandi\s+\$\w+\s*,\s*\$\w+\s*,\s*' + mask + r'\b', asm, re.I))
            if target >= len(uses):
                continue
            text = source
            for m in reversed(uses):
                text = text[:opening + m.start()] + param + text[opening + m.end():]
            result.append((FAMILY, text))
    return result[:4]

"""m2c's `E & K & (comparison)` with the `!= 0` it dropped put back: as written it is always 0.

`(E & 0xC00) != 0` AND-ed with `arg1 != NULL` comes back from m2c as `E & 0xC00 & (arg1 != NULL)`. A comparison is 0
or 1, so with an even mask the whole test is constant 0, and gcc deletes everything it guards: an N64 function kept 51
of the game's 251 instructions (18.9% -> 50.2% with the comparison back). Exact in meaning against the game's code,
which sets both truth values (`sltu`) and ANDs them.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'masked_flag_test'
FAMILIES = (FAMILY,)

NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    text = source
    hits = list(re.finditer(r'\bif\s*\(', clean[opening:end]))
    for hit in reversed(hits):
        cond_open = opening + hit.end() - 1
        cond_close = close(clean, cond_open)
        if not cond_close:
            continue
        cond = source[cond_open + 1:cond_close - 1]
        m = re.fullmatch(r'\s*(?P<value>.+?)\s*&\s*(?P<mask>' + NUMBER + r')\s*&\s*(?P<test>\([^()]*(?:!=|==|<=|>=|<|>)[^()]*\))\s*', cond)
        if not m or int(m['mask'], 0) % 2:
            continue
        fixed = f"(({m['value']} & {m['mask']}) != 0) & {m['test']}"
        text = text[:cond_open + 1] + fixed + text[cond_close - 1:]
    return [(FAMILY, text)] if text != source else []

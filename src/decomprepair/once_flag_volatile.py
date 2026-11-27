"""A set-once init flag the game declared `volatile`.

`if (flag == 0) { flag = 1; create...(); }` (or the early `return`): gcc moves the plain store into the delay slot of the
first call. A target that has the `sw` before the `jal`, with something else in the delay slot, stored a `volatile` flag
(libultra-style manager start-ups guard themselves this way). Measured on a 58-instruction N64 device-manager start-up
(SN gcc 2.8.1): 120 with the plain flag, exact with `extern volatile s32 flag;`.

`scalar_reload_volatile` covers a global stored and read back; this flag is read only by the guard, before the store.
`volatile` only keeps accesses in place, so the meaning stays. The family `once_flag_volatile` offers it for each extern
scalar integer the function tests against zero and then assigns a constant."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'once_flag_volatile'
FAMILIES = (FAMILY,)
EXTERN = re.compile(r'(?m)^[ \t]*extern\s+(?P<type>(?:(?:unsigned|signed)\s+)?(?:u8|s8|u16|s16|u32|s32|int|short|char|long))'
                    r'\s+(?P<g>[A-Za-z_]\w*)\s*;')
LIMIT = 4


def _once_flag(body, glob):
    g = re.escape(glob)
    test = re.search(rf'\bif\s*\(\s*(?:!\s*{g}|{g}\s*(?:==|!=)\s*0)\s*\)', body)
    if not test or re.search(rf'&\s*{g}\b(?!\s*&)|\b{g}\s*\[', body):
        return False
    return bool(re.search(rf'(?<![\w.>*])\b{g}\s*=\s*(?:0[xX][0-9a-fA-F]+|\d+|TRUE)[uU]?\s*;', body[test.end():]))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    found = [decl for decl in EXTERN.finditer(clean, 0, span[0])
             if not re.search(r'(?m)^[ \t]*#\s*define[^\n]*\b' + decl['g'] + r'\b', clean)
             and _once_flag(body, decl['g'])]
    return [(FAMILY, source[:d.start('type')] + 'volatile ' + source[d.start('type'):]) for d in found[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

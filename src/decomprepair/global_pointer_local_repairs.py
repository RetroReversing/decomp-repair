"""A global pointer the C tests and uses, held in a local from its test on.

`if (G != NULL) { M2C_FIELD(G, s32 *, 0x10) = ...; } f(G);` reloads `G` after each store through it, since the store
might change `G` itself. A source that read `G` once into a local didn't: an N64 function was 94.3% with m2c's
repeated `D_800BD554`, and exact with `p = D_800BD554;` before its test and `p` after it. The meaning changes only if
a store through the pointer can reach the global itself, which the judge's byte comparison settles.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'global_pointer_local'
FAMILIES = (FAMILY,)

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
    body = clean[opening:end]
    signature = clean[span[0]:opening]
    params = set(re.findall(r'(' + IDENT + r')\s*(?:,|\))', signature))
    locals_ = set(re.findall(r'(?m)^[ \t]*(?:[\w ]+?)[\s*]+(' + IDENT + r')\s*(?:\[[^]]*\])?\s*;', body))
    result = []
    for test in re.finditer(r'(?m)^(?P<indent>[ \t]*)if\s*\(\s*(?P<g>' + IDENT + r')\s*!=\s*(?:NULL|0)\s*\)\s*\{', body):
        g = test['g']
        if g in params or g in locals_ or g.startswith('__repair'):
            continue
        rest = body[test.start():]
        uses = [m.start() for m in re.finditer(r'(?<![\w.>])' + g + r'\b', rest)]
        # tested, then used through or passed on at least twice more; never assigned or its address taken
        if len(uses) < 3 or re.search(r'(?<![\w.>])' + g + r'\s*=(?!=)|&\s*' + g + r'\b', body):
            continue
        # a call between the test and the last use could change the global: only calls that take it are allowed
        last = test.start() + uses[-1]
        between = body[test.start():last]
        calls = [c for c in re.finditer(r'\b(' + IDENT + r')\s*\(', between) if c[1] not in ('M2C_FIELD', 'if')]
        start = test.start()
        if any(g not in body[start + c.end():close(body, start + c.end() - 1) or len(body)] for c in calls):
            continue
        local = '__repair_' + g
        text = source
        for p in reversed(uses):
            at = opening + test.start() + p
            text = text[:at] + local + text[at + len(g):]
        at = opening + test.start()
        text = text[:at] + f'{test["indent"]}{local} = {g};\n' + text[at:]
        text = text[:opening + 1] + f'\n    void *{local};' + text[opening + 1:]
        result.append((FAMILY, text))
        if len(result) >= 4:
            break
    return result

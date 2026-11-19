"""A global pointer the game reloaded at each use, declared `volatile`.

gcc keeps a global it has tested in a register for the store that follows; the game loaded it again (`lui`, `lw
%lo(D)` before the test and again before the store). Two N64 functions that test a pointer and then store through
it were 94.8% and 95.7% so and exact with the pointer `volatile`. Offered for a global whose `%lo` loads in the
target are as many as its mentions in the function, and more than one.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'reloaded_global'
FAMILIES = (FAMILY,)


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    outside = clean[:span[0]]
    result = []
    for decl in re.finditer(r'(?m)^[ \t]*extern\s+(?P<type>[\w ]+?\s*\*+)\s*(?P<g>[A-Za-z_]\w*)\s*;', outside):
        g = decl['g']
        if 'volatile' in decl.group(0):
            continue
        loads = len(re.findall(r'\blw\s+\$\w+\s*,\s*%lo\(\s*' + re.escape(g) + r'\s*\)', asm))
        mentions = len(re.findall(r'\b' + re.escape(g) + r'\b', clean[opening:end]))
        if loads < 2 or loads != mentions:
            continue
        text = source[:decl.end('type')] + 'volatile ' + source[decl.start('g'):]
        result.append((FAMILY, text))
    return result[:3]

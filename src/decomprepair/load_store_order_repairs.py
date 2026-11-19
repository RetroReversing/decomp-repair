"""A load through a pointer written before the global store m2c put ahead of it.

gcc may not move a load through a pointer above a store to a global that the pointer could alias, so the order of
the two statements in the C is the order of the instructions. m2c follows the order the stores appear, and a load
the game did first lands after the store:

    D_800E1A68 = 0;
    D_800C7E6C = M2C_FIELD(arg0, u8 *, 0x44);

An N64 function was 96.2% this way and exact with the two statements swapped. The swap changes meaning only when the
pointer reaches the global, which is what the judge's byte comparison settles.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'load_before_store'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
STATEMENT = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>' + IDENT + r')\s*=(?!=)\s*(?P<rhs>[^;{}]*);[ \t]*\n')
LOAD = re.compile(r'\bM2C_FIELD\s*\(|->|\*\s*\(|\[')


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
    locals_ = set(re.findall(r'(?m)^[ \t]*(?:[\w ]+?)[\s*]+(' + IDENT + r')\s*(?:\[[^]]*\])?\s*;', body))
    result = []
    for first in STATEMENT.finditer(clean, opening + 1, end):
        second = STATEMENT.match(clean, first.end())
        if not second or second['indent'] != first['indent']:
            continue
        stored, value = first['lhs'], first['rhs']
        # a global stored with a plain value (no load, no call), then a statement that loads through a pointer
        if stored in locals_ or LOAD.search(value) or re.search(IDENT + r'\s*\(', value):
            continue
        if not LOAD.search(second['rhs']) or re.search(IDENT + r'\s*\(', second['rhs'].replace('M2C_FIELD(', '')):
            continue
        if re.search(r'\b' + re.escape(stored) + r'\b', second.group(0)) \
                or re.search(r'\b' + re.escape(second['lhs']) + r'\b', first.group(0)):
            continue
        text = (source[:first.start()] + source[second.start():second.end()] + source[first.start():first.end()]
                + source[second.end():])
        result.append((FAMILY, text))
        if len(result) >= 4:
            break
    return result

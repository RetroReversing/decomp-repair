"""A local `f32 pos[2];` declared as the three-component vector it was: `f32 pos[3];`.

A point the original kept in memory is often a three-component vector of which this function uses only `x` and `y`. A
draft that declares the two it saw leaves the frame 8 bytes smaller than the target's, with every saved register lower.
A particle-quad builder (SN GCC 2.8.1, `-G0 -mips3 -O2`, a 205-instruction N64 function; one function, 6 -> 0) was exact
with `pos[3]`. An unused padding object also sizes the frame, but the game's source had no such object.

Only for a local float array of two whose every use is a literal index 0 or 1. One child for each such array. The third
element is never read or written, so the meaning is the same. A candidate rewrite; the judge decides.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'float_pair_vec3'
FAMILIES = (FAMILY,)
LIMIT = 4
DECLARATION = re.compile(rf'(?m)^[ \t]*(?:f32|float)\s+(?P<name>{IDENT})\s*\[\s*(?P<count>2)\s*\]\s*;')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    result = []
    for hit in DECLARATION.finditer(part.clean, part.opening, part.end):
        array = hit['name']
        named = len(re.findall(rf'\b{array}\b', part.body))
        indexed = len(re.findall(rf'\b{array}\s*\[\s*[01]\s*\]', part.body))
        # the declaration itself names the array once and is not a `[0]`/`[1]` use
        if named < 2 or indexed != named - 1:
            continue
        result.append((FAMILY, source[:hit.start('count')] + '3' + source[hit.end('count'):]))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 120}

"""A narrow value kept in a loop counter that no loop needs at that point, its reads cast back.

    u16 colour;
    ...
    colour = 0xFF;
    ...
    colour = 0x80;
    set_colour(gfxp, colour, colour, colour);
    for (j = 0; j < 8; j++) { .. }

The game wrote the colour into the counter itself: `j = 0xFF; .. set_colour(gfxp, (u16)j, (u16)j, (u16)j);`. One pseudo
for both takes the register the call's arguments want, and the counter's loops move with it. Two N64 menu renderers
(KMC GCC 2.7.2 -O1) needed it: 290 -> 0 and 90 -> 0 on the exact judge, the same step both times. The register reading
is a hypothesis (not confirmed in the compiler source).

`disjoint_scalar_merge` does the merge for two locals of one type in a function without `switch`; this is the narrow
case with the casts, `switch` allowed.

Children (`narrow_value_in_counter`, bounded): for each `u8`/`u16`/`s16` local that is set before it is read and each
`s32`/`u32` local that a `for` counts, where the counter holds nothing across the narrow value's mentions: the counter
between the first and last of them is not mentioned, and its next mention after them, if any, sets it.
"""
import re

from .csource import _blank, find

FAMILY = 'narrow_value_in_counter'
FAMILIES = (FAMILY,)
LIMIT = 6
NARROW = re.compile(r'(?m)^[ \t]*(u8|u16|s16)[ \t]+([A-Za-z_]\w*);[ \t]*\n')
WIDE = re.compile(r'(?m)^[ \t]*(?:s32|u32|int)[ \t]+([A-Za-z_]\w*);[ \t]*\n')


def variants(source, name):
    return [(FAMILY, text) for text in rewrites(source, name)]


def _mentions(clean, word, lo, hi):
    return list(re.compile(rf'(?<![\w.])(?<!->){word}\b').finditer(clean, lo, hi))


def _sets(clean, hit):
    """The mention is the left side of a plain `=`."""
    return re.match(r'\s*=(?!=)', clean[hit.end():hit.end() + 40]) is not None


def rewrites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0 or re.search(r'\bgoto\b', clean[opening:end]):
        return []
    counters = []
    for hit in WIDE.finditer(clean, opening, end):
        if re.search(rf'\bfor\s*\(\s*{hit[1]}\s*=', clean[opening:end]):
            counters.append((hit[1], hit))
    result = []
    for decl in NARROW.finditer(clean, opening, end):
        kind, narrow = decl[1], decl[2]
        uses = _mentions(clean, narrow, decl.end(), end)
        if not uses or not _sets(clean, uses[0]):
            continue
        if re.search(rf'(?:&\s*|\+\+|--){narrow}\b|\b{narrow}\s*(?:\+\+|--|[-+*/%|&^]=|<<=|>>=)', clean[opening:end]):
            continue
        first, last = uses[0].start(), uses[-1].end()
        for counter, counter_decl in counters:
            if re.search(rf'&\s*{counter}\b', clean[opening:end]):
                continue
            others = _mentions(clean, counter, counter_decl.end(), end)
            if any(first <= hit.start() < last for hit in others):
                continue
            later = [hit for hit in others if hit.start() >= last]
            if later and not _sets(clean, later[0]):
                continue
            pieces, at = [], 0
            for use in uses:
                pieces.append(source[at:use.start()])
                pieces.append(counter if _sets(clean, use) else f'({kind}){counter}')
                at = use.end()
            pieces.append(source[at:])
            text = ''.join(pieces)
            text = text[:decl.start()] + text[decl.end():]
            if text not in result:
                result.append(text)
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}

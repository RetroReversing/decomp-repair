"""Two locals of one type whose lives never overlap, written as one variable.

m2c names each value it recovers: a loop counter, then the same register's next role as a second counter, an
accumulator's first value and its clamped value as three names. GCC 2.7.2 hands the saved registers out by
`floor_log2(uses) * uses / live_length`, one pseudo per source variable, so what the draft split into three small
pseudos is one long one in the original, and it is the sum of the uses and the longer range that decides which
register it gets. Merging a late local into an early one of the same type, when the early one is never mentioned
after the late one's first mention, reproduced that for a counter shared by three loops (a counter's priority
passed two offsets'), an accumulator chain of three clamps and the register of a loop's index (a 719-instruction N64
function, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`: 5420 -> 5390, 5390 -> 5205, 3255 -> 3075, 1765 -> 1750 for
the four merges). The pairs are scored by the closeness of their last and first mentions; a merge is dropped when both
sit in one loop body (the earlier value could be carried round it). A candidate rewrite; the exact judge decides.

Two more cases, from a 565-instruction N64 text renderer (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) whose
`switch` inside the character loop held a colour word in two case arms (an `unsigned` read through `>> 24`) and, in the
default arm, a glyph index (`signed`). The game used one variable for both: the shared pseudo is allocated by global.c
as one long one, and the colour word took `$t2` like the index, where two private pseudos took `$a2` (24 rows of the
byte difference). Both were out of reach before:

* the two locals had different 32-bit types (`u32` and `s32`): the pair is also offered when both are one of
  `s32`/`u32`/`int`/`unsigned`, once keeping the earlier declaration's type and once the later one's, because the
  colour word needs the logical shift of the unsigned type and the index only needs an integer;
* both lived in one loop body, which dropped the merge: when the first mention of each is a plain assignment
  (`name = ...;` at the start of a statement) neither value can come round the loop from the other's role, so the
  pair stays. A pair whose later local is read before it is assigned in the loop is still dropped.
"""
import re

from .integer_repair_support import locals_for, view
from .line_scan import apply, lines, loops

FAMILY = 'disjoint_local_merge'
FAMILIES = (FAMILY,)
LIMIT = 12
WORD = {'s32', 'u32', 'int', 'unsigned', 'unsigned int', 'signed int'}


def _assigned_first(part, name, start):
    """Whether the first mention of `name` at or after `start` is a plain `name = ...;` assignment statement."""
    first = re.search(rf'(?<![\w.>]){re.escape(name)}\b', part.clean[start:part.end])
    if not first:
        return False
    at = start + first.start()
    before = part.clean[part.opening + 1:at].rstrip()
    return (not before or before[-1] in ';{}:') and re.match(rf'{re.escape(name)}\s*=(?!=)', part.clean[at:at + len(name) + 6]) is not None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    decls = locals_for(part)
    if len(decls) < 2:
        return []
    body = lines(part, source)
    spans = [(body[do].start, body[w].end) for do, _, _, w in loops(body)]
    use = {}
    for decl in decls:
        hits = [m.start() for m in re.finditer(rf'(?<![\w.>]){re.escape(decl["name"])}\b', part.clean[decl.end():part.end])]
        if hits:
            use[decl['name']] = (decl.end() + hits[0], decl.end() + hits[-1])
    ranked = []
    for early in decls:
        for late in decls:
            a, b = early['name'], late['name']
            same = early['type'] == late['type']
            if a == b or not (same or {early['type'], late['type']} <= WORD) or a not in use or b not in use:
                continue
            if not use[a][1] < use[b][0]:
                continue
            if any(s <= use[a][1] and use[b][0] <= e for s, e in spans):
                if not (_assigned_first(part, a, early.end()) and _assigned_first(part, b, late.end())):
                    continue
            ranked.append((use[b][0] - use[a][1], a, b, early, late))
    ranked.sort(key=lambda item: item[:3])
    out = []
    for _, a, b, early, late in ranked[:LIMIT]:
        edits = [(late.start(), late.end(), '')]
        for m in re.finditer(rf'(?<![\w.>]){re.escape(b)}\b', part.clean[late.end():part.end]):
            edits.append((late.end() + m.start(), late.end() + m.end(), a))
        out.append((FAMILY, apply(source, edits)))
        if early['type'] != late['type']:
            # the survivor takes the later local's type too (a logical shift or compare needs the unsigned one)
            retyped = [(early.start('type'), early.end('type'), late['type'])]
            out.append((FAMILY, apply(source, edits + retyped)))
    return out

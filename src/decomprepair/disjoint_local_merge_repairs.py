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
"""
import re

from .integer_repair_support import locals_for, view
from .line_scan import apply, lines, loops

FAMILY = 'disjoint_local_merge'
FAMILIES = (FAMILY,)
LIMIT = 12


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
            if a == b or early['type'] != late['type'] or a not in use or b not in use:
                continue
            if not use[a][1] < use[b][0]:
                continue
            if any(s <= use[a][1] and use[b][0] <= e for s, e in spans):
                continue
            ranked.append((use[b][0] - use[a][1], a, b, late))
    ranked.sort(key=lambda item: item[:3])
    out = []
    for _, a, b, late in ranked[:LIMIT]:
        edits = [(late.start(), late.end(), '')]
        for m in re.finditer(rf'(?<![\w.>]){re.escape(b)}\b', part.clean[late.end():part.end]):
            edits.append((late.end() + m.start(), late.end() + m.end(), a))
        out.append((FAMILY, apply(source, edits)))
    return out

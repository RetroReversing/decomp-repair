"""Two calls of one function, written in the other order in one arm than in its peers.

A display-list builder expands the same macro in every arm: `a = size_log(h); b = size_log(w);` (two calls of one helper
with the height and the width) once per tile command. m2c writes the pair in the order the registers were read, which
is not always the order the original had, so one arm of four has `b = f(w); a = f(h);`. The calls run in source order,
which sets which result takes which register and where the loads between them land.

Offered only when the evidence is in the function itself: two adjacent statements `x = f(p);` and `y = f(q);` (the same
callee, plain identifier arguments `p != q`, no other effect) whose arguments appear in the same pair in at least three
places, with one order in strictly more places than the other. Each minority pair is turned round to the majority's
order (the hypothesis: the arms came from one macro; the judge decides). That the callee's two calls are independent
of each other's order is also an assumption.

`variants` gives, labelled `call_pair_order_peers`, one child per odd pair and one with all of them turned round.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'call_pair_order_peers'
FAMILIES = (FAMILY,)
LIMIT = 8
ID = r'[A-Za-z_]\w*'
PAIR = re.compile(rf'(?m)^(?P<i1>[ \t]*)(?P<x>{ID})\s*=\s*(?P<f>{ID})\s*\(\s*(?P<p>{ID})\s*\)\s*;[ \t]*\n'
                  rf'(?P<i2>[ \t]*)(?P<y>{ID})\s*=\s*(?P=f)\s*\(\s*(?P<q>{ID})\s*\)\s*;[ \t]*\n')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    groups = {}
    for hit in PAIR.finditer(part.clean, part.opening + 1, part.end):
        if hit['p'] == hit['q'] or hit['x'] == hit['y']:
            continue
        key = (hit['f'], frozenset((hit['p'], hit['q'])))
        groups.setdefault(key, []).append(hit)
    swaps = []
    for hits in groups.values():
        if len(hits) < 3:
            continue
        orders = {}
        for h in hits:
            orders.setdefault((h['p'], h['q']), []).append(h)
        if len(orders) != 2:
            continue
        (_, low), (_, high) = sorted(orders.items(), key=lambda kv: len(kv[1]))
        if len(low) == len(high):
            continue
        swaps += low
    if not swaps:
        return []

    def turn(h):
        first = source[h.start():h.start('i2')]
        second = source[h.start('i2'):h.end()]
        return (h.start(), h.end(), second + first)

    out = [edit(source, [turn(h)]) for h in swaps]
    if len(swaps) > 1:
        out.append(edit(source, [turn(h) for h in swaps]))
    return [(FAMILY, c) for c in dict.fromkeys(out) if c != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 67}

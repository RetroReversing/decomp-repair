"""A value masked in a loop's test every pass, masked in place before the loop.

m2c keeps an invariant mask inside the comparison it found it in:

    key = *src++;                                  key = *src++;
    p = table;                                     key &= 0x1FFE000;
    size = 0x1000;                       ->        p = table;
    for (;;) {                                     size = 0x1000;
        v = *p;                                    for (;;) {
        if (v != (key & 0x1FFE000)) {                  v = *p;
                                                       if (v != key) {

The loop pass would hoist `key & M` into a new register after the loop's set-up. A target that masks the loaded
register itself (`and $a3, $a3, $t8`) before the set-up wrote `key &= M;`. Offered only for a local that is named
nowhere but its declaration, plain assignments before the loop and that one test, so the in-place update changes
nothing. Children put the update ahead of the loop's plain set-up assignments and right before the loop.

On an 84-instruction N64 table-setup loop (SN64 GCC 2.8.1, `-G0 -mips3 -O2`) this was the last step, 270 -> 0 (one
function). The candidate is never a verdict: the judge decides."""
import re

from .hoisted_invariant_inline import _loops
from .integer_repair_support import IDENT, INTEGER, NUMBER, _address_taken, edit, view

FAMILY = 'loop_mask_in_place'
FAMILIES = (FAMILY,)
_MASKED = re.compile(rf'(?:!=|==)\s*(?P<whole>\(\s*(?P<v>{IDENT})\s*&\s*(?P<mask>{NUMBER})\s*\))')
_HEAD = re.compile(r'(?:\bfor\s*\([^(){}]*\)|\bwhile\s*\([^{};]*\)|\bdo)\s*\Z')
_SETUP = re.compile(rf'(?<=[;{{}}])\s*(?P<name>{IDENT})\s*=(?!=)[^;{{}}]*;\s*\Z')
LIMIT = 8


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    loops = _loops(clean, part.opening + 1, part.end - 1)
    out = []
    for hit in _MASKED.finditer(clean, part.opening, part.end):
        value = hit['v']
        inside = [(brace, end) for brace, end in loops if brace < hit.start() < end]
        if not inside:
            continue
        brace = max(inside)[0]
        head = _HEAD.search(clean, part.opening, brace)
        if not head or not re.search(rf'\b{INTEGER}\s+{value}\s*;', body) or _address_taken(body, value):
            continue
        start = head.start()
        sets = [m for m in re.finditer(rf'(?<=[;{{}}])\s*{value}\s*=(?!=)[^;{{}}]*;', clean[:start])
                if m.start() >= part.opening and value not in m.group().split('=', 1)[1]]
        if not sets or len(re.findall(rf'\b{value}\b', body)) != len(sets) + 2:
            continue
        setup = start
        while (before := _SETUP.search(clean, part.opening, setup)) and before['name'] != value:
            setup = before.start()
        places = [start]
        if setup != start:
            places.insert(0, setup + len(clean[setup:start]) - len(clean[setup:start].lstrip()))
        for place in places:
            if place <= sets[-1].start():
                continue
            line = source[source.rfind('\n', 0, place) + 1:place]
            indent = line if not line.strip() else ''
            out.append((FAMILY, edit(source, [(place, place, f'{value} &= {hit["mask"]};\n{indent}'),
                                              (hit.start('whole'), hit.end('whole'), value)])))
        if len(out) >= LIMIT:
            break
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

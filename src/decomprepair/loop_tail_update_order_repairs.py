"""The order of a loop's last two counter updates (`i += 1; offset += 0x1A0;` versus the reverse).

GCC 2.7's second scheduler may move an independent add up past a run of stores, so the order the two updates are
written in decides which one ends up at the loop's top and which stays at its tail. A table-clearing loop whose
target steps `i` just before the compare (`addiu $a1,$a1,1; slti; bnez; addiu $v1,$v1,0x1a0` in the delay slot) came
out with the `i` step hoisted to the loop's top until the two updates were written offset first, then `i`. Both
loops of that function needed it at once (120 -> 60 -> 0), so the pair of loops is offered as one child too.

Only `v += n;`, `v -= n;`, `v++;`/`++v;` (and `--`) on two different plain locals that are the last two statements
of a `do { } while` body are swapped; the compiler and the byte judge decide."""
import re

from .integer_repair_support import IDENT, edit, view
from .loop_address_hoist_repairs import _loops

FAMILIES = ('loop_tail_update_order',)
LIMIT = 24
STEP = rf'(?:{IDENT}\s*(?:[+-]=\s*(?:0[xX][0-9A-Fa-f]+|\d+)|\+\+|--)|(?:\+\+|--)\s*{IDENT})\s*;'
TAIL = re.compile(rf'(\s*)({STEP})(\s*)({STEP})(\s*)\}}\s*while\s*\(')


def _target(text):
    return re.search(IDENT, text)[0]


def _swaps(clean, lo, hi):
    found = []
    for start, end in _loops(clean, lo, hi):
        if not re.match(r'do\s*\{', clean[start:end]):
            continue
        for m in TAIL.finditer(clean, start, end):
            if _target(m[2]) != _target(m[4]):
                found.append(m)
    return found


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    swaps = _swaps(part.clean, part.opening, part.end)
    singles = []
    for m in swaps:
        first, second = (m.start(2), m.end(2)), (m.start(4), m.end(4))
        singles.append([(first[0], second[1], source[second[0]:second[1]] + source[first[1]:second[0]]
                         + source[first[0]:first[1]])])
    out = [edit(source, e) for e in singles]
    if len(singles) > 1:
        out.append(edit(source, [x for e in singles for x in e]))
    return [(FAMILIES[0], c) for c in out[:LIMIT] if c != source]

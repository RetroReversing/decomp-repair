"""A negation in place, written as a multiply by -1 (and the other way round).

`p->dir = -p->dir;` on an `s8` or `s16` loads with `lbu`/`lhu`: only the low bits survive the store, so gcc takes the
unsigned load. `p->dir *= -1;` computes in `int` and keeps the signed load (`lb`/`lh`). Measured on one function (KMC
GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`): the last differing row, `lbu` against the target's `lb`, 200 -> 0. Why gcc
picks each load is a hypothesis; the pair of rows is measured."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'narrow_negate_multiply'
FAMILIES = (FAMILY,)
LIMIT = 16
# a name, then any run of member accesses and subscripts without calls or side effects
_PLACE = rf'{IDENT}(?:[ \t]*(?:->|\.)[ \t]*{IDENT}|[ \t]*\[[ \t]*(?:{IDENT}|\d+|0x[0-9A-Fa-f]+)[ \t]*\])*'
_NEGATE = re.compile(rf'(?<![\w\].>])(?P<place>{_PLACE})[ \t]*=[ \t]*-[ \t]*(?P=place)[ \t]*;')
_MULTIPLY = re.compile(rf'(?<![\w\].>])(?P<place>{_PLACE})[ \t]*\*=[ \t]*-[ \t]*1[ \t]*;')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    edits = []
    for pattern, spelling in ((_NEGATE, '{} *= -1;'), (_MULTIPLY, '{0} = -{0};')):
        for hit in pattern.finditer(part.clean, part.opening, part.end):
            before = part.clean[:hit.start()].rstrip()
            # a statement of its own: not the tail of `*p = -p;`, `(s8) a = ...` or `if (x) a`
            if before[-1:] not in (';', '{', '}', ')', ':'):
                continue
            place = source[hit.start('place'):hit.end('place')]
            edits.append((hit.start(), hit.end(), spelling.format(place)))
    result = [(FAMILY, edit(source, [one])) for one in edits[:LIMIT]]
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

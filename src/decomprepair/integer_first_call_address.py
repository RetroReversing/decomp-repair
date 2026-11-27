"""A byte address passed to a call with the integer first: `f(k + base)` as `f((u8 *)(k + (s32) base))`.

    f(k + base);     /* base a byte pointer */     ->     f((u8 *)(k + (int) base));

GCC 2.7.2 builds pointer plus integer with the pointer as the add's first operand (`addu $a0, $s1, $a0`) whichever side
the source writes it, so a target with the offset first (`addu $a0, $a0, $s1`, the last row of a 282-instruction state
machine, 5 -> 0) needs the sum done in integers. Offered for each call argument that is a byte pointer local plus an
integer local, in either order, one site per child. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'integer_first_call_address'
FAMILIES = (FAMILY,)
_POINTER = re.compile(rf'\b(?P<type>u8|s8|char|unsigned\s+char|signed\s+char)\s*\*\s*(?P<name>{IDENT})\s*[;=,)]')
_ARGUMENT = re.compile(rf'(?<=[(,])\s*(?P<a>{IDENT})\s*\+\s*(?P<b>{IDENT})\s*(?=[,)])')
_INTEGER = r'(?:u8|s8|u16|s16|u32|s32|int|short|long|unsigned|size_t)'
LIMIT = 6


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pointers = {m['name']: ' '.join(m['type'].split()) for m in _POINTER.finditer(clean, 0, part.end)}
    if not pointers:
        return []
    integers = {m[1] for m in re.finditer(rf'\b{_INTEGER}(?:\s+(?:int|long|short|char))*\s+({IDENT})\s*[;=,)]',
                                          clean[:part.end])}
    out = []
    for hit in _ARGUMENT.finditer(clean, part.opening, part.end):
        a, b = hit['a'], hit['b']
        pointer, offset = (a, b) if a in pointers else (b, a)
        if pointer not in pointers or offset not in integers or offset in pointers:
            continue
        text = f'({pointers[pointer]} *)({offset} + (int) {pointer})'
        out.append((FAMILY, edit(source, [(hit.start('a'), hit.end('b'), text)])))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}

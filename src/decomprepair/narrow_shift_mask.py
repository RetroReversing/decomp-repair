"""A right shift of a narrow (`u8`/`u16`) variable masked to the bits it can have: no instruction, a longer life.

GCC 2.x's flow.c counts every register's life in the instructions before combine runs, and global.c orders allocnos
by `floor_log2(refs) * refs / live length`. `(v >> K) & M`, with `v` a `u16` and `M` the `16 - K` bits the shift can
leave, is not folded by cse but is deleted by combine (its nonzero-bits analysis knows the mask is a no-op), so it
compiles to the same instructions while each value live across it lives one instruction longer.

A 681-instruction N64 bit-stream decoder (KMC GCC 2.7.2 `-O2`): `(ent >> 7) & 0x1FF` in a subtable's address,
`ent` a `u16`, lengthened a loop-made pointer copy's life by one instruction with no change in code; one of the
spellings that move such a copy below a competitor in global.c's order.

Child, for each `(V >> K)` (or `V >> K` as a whole operand) where `V` is declared `u8`/`u16`/`unsigned char`/
`unsigned short` in the function and `0 < K < width`: that shift written `((V >> K) & M)`. Mask already present: left.
The candidate is never a verdict: the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'narrow_shift_mask'
FAMILIES = (FAMILY,)
LIMIT = 8
_WIDTH = {'u8': 8, 'unsigned char': 8, 'u16': 16, 'unsigned short': 16}
_DECL = re.compile(r'\b(u8|u16|unsigned\s+char|unsigned\s+short)\s+([^;()]+);')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    narrow = {}
    for m in _DECL.finditer(clean, part.opening, part.end):
        width = _WIDTH[re.sub(r'\s+', ' ', m.group(1))]
        for item in m.group(2).split(','):
            v = re.match(rf'\s*({IDENT})\s*(?:=|$)', item)
            if v:
                narrow[v.group(1)] = width
    out = []
    for var, width in narrow.items():
        for m in re.finditer(rf'\(\s*{re.escape(var)}\s*>>\s*(\d+)\s*\)', clean[:part.end]):
            if m.start() < part.opening:
                continue
            k = int(m.group(1))
            if not 0 < k < width or re.match(r'\s*&', clean[m.end():]):
                continue
            mask = (1 << (width - k)) - 1
            out.append((FAMILY, edit(source, [(m.start(), m.end(), f'({source[m.start():m.end()]} & 0x{mask:X})')])))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

"""A word read narrowed to a halfword, next to a halfword read of the same offset: the two adjacent halfword fields.

m2c shows one word at `0x30(p)` read twice, once through `(s16)` and once as a halfword at the same offset:

    a = (s16) FIELD(p, s32 *, 0x30) + x;      b = FIELD(p, s16 *, 0x30) + y;

On big-endian MIPS the narrowed word is the low half, the halfword at `0x32`; the game kept a record of two `s16`
fields at `0x30` and `0x32`, each read with `lh`, and the second statement reads the neighbour, not the same half again.
Measured on a KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) N64 function that adds a velocity pair to a position pair
(3640 -> ... -> 0 over the whole match; this was the last 20): the first `+=` reads `s16 @ 0x30`, the second `s16 @ 0x32`.

One child per pair, in two spellings: `narrow` rewrites only the narrowed word into the halfword it really is (`s16` at
the offset + 2, the same value on a big-endian target); `pair` also moves the plain halfword to the neighbour, so
the statements read `0x30` and `0x32` in turn (the target's order). The second is not value-preserving by itself: the
exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'adjacent_halfword_fields_narrow'
PAIR = 'adjacent_halfword_fields_pair'
FAMILIES = (FAMILY, PAIR)

OFFSET = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)'
NARROWED = re.compile(rf'\(s16\)\s*M2C_FIELD\((?P<p>{IDENT}),\s*s32 \*,\s*(?P<n>{OFFSET})\)')
HALFWORD = re.compile(rf'M2C_FIELD\((?P<p>{IDENT}),\s*(?P<t>[su]16) \*,\s*(?P<n>{OFFSET})\)')


def _number(text, like):
    value = int(text, 0)
    return value, (lambda v: f'0x{v:X}') if like.lower().startswith('0x') else (lambda v: str(v))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for narrowed in NARROWED.finditer(clean, part.opening, part.end):
        offset, spell = _number(narrowed['n'], narrowed['n'])
        if offset % 4:
            continue
        word = f'M2C_FIELD({narrowed["p"]}, s16 *, {spell(offset + 2)})'
        twins = [h for h in HALFWORD.finditer(clean, part.opening, part.end)
                 if h['p'] == narrowed['p'] and int(h['n'], 0) == offset]
        if not twins:
            continue
        child = edit(source, [(narrowed.start(), narrowed.end(), word)])
        out.append((FAMILY, child))
        # `pair`: the narrowed word reads the halfword at the offset (the first field), the plain read the neighbour.
        for twin in twins:
            neighbour = f'M2C_FIELD({twin["p"]}, {twin["t"]} *, {spell(offset + 2)})'
            first = f'M2C_FIELD({narrowed["p"]}, s16 *, {narrowed["n"]})'
            child = edit(source, [(narrowed.start(), narrowed.end(), first), (twin.start(), twin.end(), neighbour)])
            out.append((PAIR, child))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)

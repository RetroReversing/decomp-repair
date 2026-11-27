"""m2c's `x / 192` where the target shifts first: `(x >> 3) / 24`.

GCC divides a signed `x >> k` by a constant with a magic multiply and takes the sign correction from `x` (the sign of
`x >> k` is the sign of `x`), so m2c reads the multiply of `x >> k` and the `sra 31` of `x` as one `x / (d << k)`. That
is not the program for a negative `x` and it compiles to another shift. On a 67-instruction N64 routine (SN64 GCC 2.8.1,
`-G0 -mips3 -O2`) `(nextValue() >> 3) / 24` for the draft's `/ 192` was one step of an exact match (1484 -> 1219).
(`shifted_dividend_remainder` is the same misreading for a remainder.)

Children: each `A / N` with `N == d << k` (d no power of two) as `(A >> k) / d`, for each `k` the target shifts by.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .shifted_dividend_remainder import _mixed, _number, _spans, _top, _unwrapped

FAMILY = 'folded_shift_quotient'
FAMILIES = (FAMILY,)
LIMIT = 8


def _shifts(asm):
    """The amounts the target shifts right by (signed or not), the sign shift aside; None without assembly."""
    if not asm:
        return None
    return {int(hit[1], 0) for hit in re.finditer(r'\bsr[al]\s+\$?\w+\s*,\s*\$?\w+\s*,\s*(0x[0-9a-fA-F]+|\d+)', asm)
            if int(hit[1], 0) < 31}


def variants(source, name, asm=''):
    part = view(source, name)
    if not part or '/' not in part.body:
        return []
    shifts = _shifts(asm if isinstance(asm, str) else '')
    out, seen = [], set()
    for start, stop in _spans(part.clean, part.opening, part.end):
        text = part.clean[start:stop]
        places = _top(text, '/')
        if len(places) != 1 or _mixed(text) or _top(text, '*') or _top(text, '-') or _top(text, '>>'):
            continue
        divisor = _number(text[places[0] + 1:].strip())
        if divisor is None or divisor < 6 or (start, stop) in seen:
            continue
        seen.add((start, stop))
        dividend = source[start:start + places[0]].strip()
        if not re.fullmatch(rf'{IDENT}(?:\(\))?', dividend) and _unwrapped(dividend) == dividend:
            if not re.fullmatch(rf'{IDENT}\s*\(.*\)', dividend, re.S):
                dividend = f'({dividend})'
        k = 1
        while not divisor % (1 << k):
            rest = divisor >> k
            if rest & (rest - 1) and (shifts is None or k in shifts):
                out.append((FAMILY, edit(source, [(start, stop, f'({dividend} >> {k}) / {rest}')])))
            k += 1
        if len(out) >= LIMIT:
            break
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 40}

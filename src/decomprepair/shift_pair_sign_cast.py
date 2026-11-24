"""m2c's sign-extracting shift pair, `((s32) (x << 16)) >> 24`, written as the signed cast it was: `(s8) (x >> 8)`.

m2c writes a signed byte or halfword taken out of a word as a shift up to the sign bit and an arithmetic shift down.
The game wrote the cast; both compile to the same `sll`/`sra`, but combine (KMC GCC 2.7.2) does not see them alike
when the value feeds a sum that is later compared as a `u16`. Observed (one function and its snippets, `-G0 -O2`):

    *(u16 *) (p + 0x50) = p[0xC1] + (((s32) (D << 0x10)) >> 0x18);
    sum = *(u16 *) (p + 0x50);                 /* s16 */
    if ((sum << 16) >= 0) { t = sum; if (t >= 0x80) t = 0x7F; } else t = 0;

with the shift pair the clamp's compare is `sltu` on the sum's register; with `(s8) (D >> 8)` combine keeps the
`andi $v0, $v1, 0xffff` the target has before the `sltiu` (a sound-sequence interpreter's pan clamp, 105 -> 0).
Hypothesis: combine's nonzero bits for the `ashiftrt (ashift x 16) 24` chain stop at the byte, so the u16 compare's
zero extension is folded; the cast's `sign_extend` keeps the high bits possibly nonzero.

Children: each shift pair `((s32) (X << L)) >> R` (L < R, R in 24 or 16) written as `((s8) (X >> (24 - L)))` or
`((s16) (X >> (16 - L)))`, one at a time and all together. X must be an unsigned word expression (a declared `u32`
global or local, or a `(u32)` cast), so the logical shift keeps the bits the pair kept. Proposals only."""
import re

FAMILIES = ('shift_pair_sign_cast',)
FAMILY = FAMILIES[0]
LIMIT = 8

_NUM = r'(0x[0-9A-Fa-f]+|\d+)'
_PAIR = re.compile(r'\(\(\(s32\) \((\(u32\) [A-Za-z_]\w*|[A-Za-z_]\w*) << ' + _NUM + r'\)\) >> ' + _NUM + r'\)')
_CAST = {24: 's8', 16: 's16'}


def _unsigned_words(text):
    return set(re.findall(r'\bu32\s+\**\s*([A-Za-z_]\w*)\s*[;\[=,)]', text))


def variants(source, name=None, header=None):
    words = _unsigned_words((header or '') + '\n' + source)
    sites = []
    for m in _PAIR.finditer(source):
        x, left, right = m[1], int(m[2], 0), int(m[3], 0)
        if right not in _CAST or not 0 < left < right:
            continue
        if not x.startswith('(u32) ') and x not in words:
            continue
        down = right - left
        inner = f'{x} >> {down}' if down != 0 else x
        sites.append((m.start(), m.end(), f'(({_CAST[right]}) ({inner}))'))
    if not sites:
        return []

    def apply(chosen):
        text = source
        for a, b, new in sorted(chosen, reverse=True):
            text = text[:a] + new + text[b:]
        return text

    out = [apply([site]) for site in sites]
    if len(sites) > 1:
        out.append(apply(sites))
    return [(FAMILY, s) for s in out[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)

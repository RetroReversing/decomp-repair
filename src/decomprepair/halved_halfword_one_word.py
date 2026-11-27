"""A signed halfword halved from the one shifted word its sign and its value both come from.

GCC expands `(s16) x / 2` as the halfword widened, the sign bit added, and an arithmetic shift. m2c writes the sign bit
from a shifted copy of the unsigned halfword and the value from a second, separate cast,

    t2 = (u32) (x << 0x10) >> 0x1F;
    t = (u16) ((s32) ((s16) x + t2) >> 1);

and the compiler folds `(u32) (x << 16) >> 31` into `srl` of the unshifted value, so the shift pair the target has
(`sll 16`, then `sra 16` for the value and `srl 31` for the sign, all from the same shifted register) comes out in
another order. On an N64 function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`, two such halvings in one function,
430 points) both halves written from one shifted word each were exact:

    u32 w = (u32) (x << 0x10); s32 h = (s32) w >> 16; h += w >> 31; D = (u16) (h >> 1);

halved_halfword_one_word
    The sign-bit statement followed at once by the halving statement (or the halving with the sign bit inline), over
    the same simple name X, becomes the braced block above writing the halving's target. The sign local must be read
    only there. When the halving is followed by `V = D;` and D is read only there, a second child stores the block's
    result in V and drops the copy. One child per site and one with every site. The judge decides each child.
"""
import re

from .integer_repair_support import IDENT, edit, locals_for, refs, view

FAMILY = 'halved_halfword_one_word'
FAMILIES = (FAMILY,)
LIMIT = 6
SIGN = r'(?:0[xX]1[fF]|31)'
SIXTEEN = r'(?:0[xX]10|16)'
U32 = r'\(\s*(?:u32|unsigned(?:\s+int)?)\s*\)'
BIT = rf'{U32}\s*\(\s*(?P<{{x}}>{IDENT})\s*<<\s*{SIXTEEN}\s*\)\s*>>\s*{SIGN}'
HALVE = (r'(?P<d>' + IDENT + r')\s*=\s*\(\s*(?:u16|unsigned\s+short)\s*\)\s*\(\s*\(\s*s32\s*\)\s*\(\s*'
         r'(?:\(\s*s16\s*\)\s*(?P<h1>' + IDENT + r')\s*\+\s*{bias1}|{bias2}\s*\+\s*\(\s*s16\s*\)\s*(?P<h2>' + IDENT
         + r'))\s*\)\s*>>\s*1\s*\)\s*;')
SPLIT = re.compile(rf'(?P<t>{IDENT})\s*=\s*' + BIT.format(x='x') + r'\s*;\s*'
                   + HALVE.format(bias1=rf'(?P<t1>{IDENT})', bias2=rf'(?P<t2>{IDENT})'))
INLINE = re.compile(HALVE.format(bias1=r'\(\s*' + BIT.format(x='b1') + r'\s*\)', bias2=r'\(\s*' + BIT.format(x='b2') + r'\s*\)'))
COPY = re.compile(rf'\s*(?P<v>{IDENT})\s*=\s*(?P<d>{IDENT})\s*;')


def _block(x, dest):
    return (f'{{ u32 w = (u32) ({x} << 0x10); s32 h = (s32) w >> 16; h += w >> 31; '
            f'{dest} = (u16) (h >> 1); }}')


def _sites(part):
    clean, found = part.clean, []
    names = {d['name']: d for d in locals_for(part)}
    lo, hi = part.opening + 1, part.end - 1
    for hit in SPLIT.finditer(clean, lo, hi):
        x, t, d = hit['x'], hit['t'], hit['d']
        if (hit['h1'] or hit['h2']) != x or (hit['t1'] or hit['t2']) != t or t not in names:
            continue
        if len(refs(part, names[t])) != 2 or d in (x, t):
            continue
        found.append((hit.start(), hit.end(), d, x))
    for hit in INLINE.finditer(clean, lo, hi):
        x = hit['b1'] or hit['b2']
        if (hit['h1'] or hit['h2']) != x or hit['d'] == x:
            continue
        found.append((hit.start(), hit.end(), hit['d'], x))
    return found


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    names = {d['name']: d for d in locals_for(part)}
    plain, folded = [], []
    for start, end, dest, x in _sites(part)[:LIMIT]:
        plain.append((start, end, _block(x, dest)))
        copy = COPY.match(part.clean, end, part.end - 1)
        if copy and copy['d'] == dest and dest in names and len(refs(part, names[dest])) == 2 and copy['v'] != x:
            folded.append((start, copy.end(), _block(x, copy['v'])))
        else:
            folded.append((start, end, _block(x, dest)))
    if not plain:
        return []
    out = [edit(source, [one]) for one in plain]
    out += [edit(source, [one]) for one, base in zip(folded, plain) if one != base]
    if len(plain) > 1:
        out.append(edit(source, plain))
        if folded != plain:
            out.append(edit(source, folded))
    return [(FAMILY, child) for child in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

"""The compiler's own sign-bias form of a signed halving, written back as the signed division it came from.

m2c reads GCC's expansion of `x / 2^k` for a signed value (add the sign bit, then shift arithmetically) as

    (s32) (x + ((u32) x >> 0x1F)) >> 1

and that spelling compiles to the same steps but not to the same registers: the sum is an expression of its own whose
operands are both read, where the division's expander reads the dividend once. On an N64 function (KMC GCC 2.7.2,
`-G0 -mips3 -mgp32 -mfp32 -O2`, 15 points, every row the loaded global sitting in `$a1` where the target has it in
`$v0`) the call argument `(s32) D + ... >> 1` was exact as `(s32) D / 2`.

sign_bias_shift_divide
    `[(s32)] (X + ((u32) X >> 31)) >> K` (the addends in either order, 31 or 0x1F, `unsigned` or `u32` for the
    inner cast, K from 1 to 30) becomes `(s32) X / 2^K` (`X / 2^K` when the original had no outer `(s32)`, since then
    its type is X's own). X is a name, optionally with member accesses and constant-free subscripts; anything with a
    side effect or a call is left alone, and so is a site whose neighbours would bind to the new `/` differently from
    to the shift. One child per site and one with every site. The judge decides each child.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'sign_bias_shift_divide'
FAMILIES = (FAMILY,)
LIMIT = 8
ATOM = rf'{IDENT}(?:\s*(?:\[[^\[\]()]*\]|\.\s*{IDENT}|->\s*{IDENT}))*'
SIGN = r'(?:0[xX]1[fF]|31)'
UNSIGNED = r'\(\s*(?:u32|unsigned(?:\s+int)?)\s*\)\s*'
BIAS = rf'\(\s*{UNSIGNED}(?P<{{n}}>{ATOM}|\(\s*{ATOM}\s*\))\s*>>\s*{SIGN}\s*\)'
SHAPE = re.compile(
    r'(?P<cast>\(\s*s32\s*\)\s*)?\(\s*(?:'
    rf'(?P<x1>{ATOM})\s*\+\s*' + BIAS.format(n='b1') + r'|'
    + BIAS.format(n='b2') + rf'\s*\+\s*(?P<x2>{ATOM}))\s*\)\s*>>\s*(?P<k>0[xX][0-9a-fA-F]+|\d+)')
LOWER_BEFORE = re.compile(r'(?:[(\[,;{}?:=^|]|&&|\|\||(?<!&)&|(?<![<>])[<>]|\breturn)$')


def _same(a, b):
    strip = lambda text: re.sub(r'\s+', '', text).strip('()')  # noqa: E731
    return strip(a) == strip(b)


def _binds_alike(clean, start, end):
    """True when the text around [start:end] gives a `/` the same operands a `>>` had."""
    before = clean[:start].rstrip()
    after = clean[end:].lstrip()
    if before and not LOWER_BEFORE.search(before[-8:]):
        return False
    return not after or after[0] not in '*/%+-.[(' and not after.startswith('->')


def _sites(part):
    clean = part.clean
    found = []
    for hit in SHAPE.finditer(clean, part.opening + 1, part.end - 1):
        x, bias = (hit['x1'], hit['b1']) if hit['x1'] else (hit['x2'], hit['b2'])
        if not _same(x, bias) or re.search(r'\+\+|--|=', x):
            continue
        k = int(hit['k'], 0)
        if not 1 <= k <= 30 or not _binds_alike(clean, hit.start(), hit.end()):
            continue
        divisor = 1 << k
        text = f'{divisor:#x}' if divisor > 0x10 else str(divisor)
        found.append((hit.start(), hit.end(), f"{'(s32) ' if hit['cast'] else ''}{' '.join(x.split())} / {text}"))
    return found


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    edits = _sites(part)[:LIMIT]
    if not edits:
        return []
    out = [edit(source, [one]) for one in edits]
    if len(edits) > 1:
        out.append(edit(source, edits))
    return [(FAMILY, child) for child in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

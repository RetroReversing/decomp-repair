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

    The same for a narrow value, where the sign bit sits in the top of a shifted copy: `(s32) ((s16) H + T) >> K` with
    the bias `T = (u32) (H << 0x10) >> 0x1F;` stated first (or inline as `((u32) (H << 0x10) >> 0x1F)`), 0x18 and
    `(s8)` for a byte, becomes `(s16) H / 2^K` and the bias statement goes (its local stays declared). On a KMC GCC
    2.7.2 `-O1 -g` N64 function with two switches of three halving arms each (430 points; the halfword field read as
    `u16` first) the two divisions `(u16) ((s16) H / 2)` were exact, the bias spelled out was 1130 even inline.
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


_SHIFTS = {'s16': ('0x10', '16'), 's8': ('0x18', '24')}
BIAS_TEXT = (r'\(\s*(?:u32|unsigned(?:\s+int)?)\s*\)\s*\(\s*(?P<h{n}>' + ATOM + r')\s*<<\s*(?P<s{n}>0[xX]1[08]|16|24)\s*\)'
             r'\s*>>\s*(?:0[xX]1[fF]|31)')
SUM = (r'\(\s*s32\s*\)\s*\(\s*\(\s*(?P<c>s16|s8)\s*\)\s*(?P<x>' + ATOM + r')\s*\+\s*(?P<t>{t})\s*\)\s*>>\s*'
       r'(?P<k>0[xX][0-9a-fA-F]+|\d+)')
STATEMENT = re.compile(r'(?P<tv>' + IDENT + r')\s*=\s*' + BIAS_TEXT.format(n='') + r'\s*;\s*'
                       r'(?P<lead>' + IDENT + r'\s*=\s*(?:\(\s*(?:u16|s16|s32|u32|s8|u8)\s*\)\s*)?)\(?\s*'
                       + SUM.format(t=IDENT) + r'\s*\)?\s*;')
INLINE = re.compile(SUM.format(t=r'\(\s*' + BIAS_TEXT.format(n='2') + r'\s*\)'))


def _narrow_text(hit, h):
    k = int(hit['k'], 0)
    if not 1 <= k <= 30:
        return None
    divisor = 1 << k
    text = f'{divisor:#x}' if divisor > 0x10 else str(divisor)
    return f"({hit['c']}) {' '.join(h.split())} / {text}"


def _narrow_sites(part):
    """The narrow value's bias statements and inline sums: (start, end, text) in the clean source."""
    clean = part.clean
    found = []
    for hit in STATEMENT.finditer(clean, part.opening + 1, part.end - 1):
        if not _same(hit['h'], hit['x']) or hit['s'] not in _SHIFTS[hit['c']]:
            continue
        if re.sub(r'\s+', '', hit['t']) != re.sub(r'\s+', '', hit['tv']):
            continue
        quotient = _narrow_text(hit, hit['x'])
        if quotient is None:
            continue
        lead = hit['lead'].rstrip()
        wrapped = lead.endswith(')')
        text = f"{lead} ({quotient});" if wrapped else f"{lead} {quotient};"
        found.append((hit.start(), hit.end(), text))
    for hit in INLINE.finditer(clean, part.opening + 1, part.end - 1):
        if not (_same(hit['h2'], hit['x']) and hit['s2'] in _SHIFTS[hit['c']]):
            continue
        quotient = _narrow_text(hit, hit['x'])
        if quotient is not None:
            found.append((hit.start(), hit.end(), quotient))
    return found


def variants(source, name):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    edits = (_sites(part) + _narrow_sites(part))[:LIMIT]
    if not edits:
        return []
    out = [edit(source, [one]) for one in edits]
    if len(edits) > 1:
        out.append(edit(source, edits))
    return [(FAMILY, child) for child in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

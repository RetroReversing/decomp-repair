"""A product with a `u16` loop counter written as a `u16` product, so the multiply reads the counter unextended.

    ty = r->y + r->th * j;           ty = r->y + (u16)(r->th * j);     tx = (u16)(r->tw * i + r->x + X);

With `u16 j` (an HImode pseudo in KMC GCC 2.7.2) every wide read of `j` is a `zero_extend`, an `andi 0xffff` before the
`mult`; the target multiplies the counter's register directly (`mult $a0,$t9` after the loop's `addiu $t9,$t9,1`). convert.c
narrows a MULT/PLUS tree that is truncated by a cast or an assignment to a narrower type (`get_unwidened` of two unsigned
halfwords), so the product is evaluated in HImode, on the raw register, and the extension moves to the product's result (one
`andi` after the `mflo`, or after the whole sum). A KMC GCC 2.7.2 sprite drawer (`-G0 -mips3 -mgp32 -mfp32 -O2`, 653
instructions) went 325 -> 280 with the second product cast and 275 with the first sum cast as well (exact judge, isolated): the
`andi` before the multiply moved, but one `andi` remains where the target has none, and the position's wide readers keep the
mask. The explanation is read from convert.c (`convert_to_integer`: MULT_EXPR needs equal signedness of the unwidened operands,
PLUS_EXPR truncates when an operand is narrower) and the dumps.

Children, for an assignment whose right-hand side holds `A * N` or `N * A` (`N` a local declared `u16`, `A` a plain name or
member access): that product as `(u16)(A * N)`; and the whole right-hand side as `(u16)(RHS)`. A product already under a
`(u16)` is left alone. The candidate is never a verdict: the judge decides.
"""
import re

from .csource import _blank, find

FAMILY = 'counter_product_cast'
FAMILY_SUM = 'counter_product_cast_sum'
FAMILIES = (FAMILY, FAMILY_SUM)
_ID = r'[A-Za-z_]\w*'
_OPERAND = rf'{_ID}(?:\s*(?:->|\.)\s*{_ID})*'
_U16_DECL = re.compile(r'(?m)^[ \t]*(?:register\s+)?(?:u16|unsigned\s+short)[ \t]+([^;(){}\n]+);')
_ASSIGN = re.compile(rf'(?<![\w.>=!<>])(?P<lhs>{_OPERAND})\s*=(?!=)\s*(?P<rhs>[^;{{}}=]*[^;{{}}=\s])\s*;')


def _counters(clean, span):
    names = set()
    for m in _U16_DECL.finditer(clean, span[0], span[1]):
        for part in m.group(1).split(','):
            ident = part.split('=')[0].strip()
            if re.fullmatch(_ID, ident):
                names.add(ident)
    return names


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    names = _counters(clean, span)
    if not names:
        return []
    alt = '|'.join(sorted(map(re.escape, names)))
    product = re.compile(rf'(?<![\w.>])(?:(?P<a>{_OPERAND})\s*\*\s*(?P<n>{alt})\b|(?P<n2>{alt})\s*\*\s*(?P<a2>{_OPERAND}))(?![\w.>(\[])')
    out = []
    for stmt in _ASSIGN.finditer(clean, span[0], span[1]):
        rhs_at = stmt.start('rhs')
        rhs = stmt['rhs']
        found = [m for m in product.finditer(rhs) if not re.search(r'\(\s*u16\s*\)\s*\($', rhs[:m.start()])]
        if not found or '(u16)' in rhs[:1]:
            continue
        for m in found:
            text = m.group(0)
            out.append((FAMILY, source[:rhs_at + m.start()] + f'(u16)({text})' + source[rhs_at + m.end():]))
        if not re.match(r'\(\s*u16\s*\)', rhs):
            out.append((FAMILY_SUM, source[:rhs_at] + f'(u16)({source[rhs_at:rhs_at + len(rhs)]})' + source[rhs_at + len(rhs):]))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}

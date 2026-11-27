"""`a * 2 * b` written as the shift the target has: `(a << 1) * b`.

m2c writes a shifted operand of a multiply as `a * 2 * b`, which GCC reassociates: it multiplies `a * b` and shifts the
product, or shifts the other operand. Written as `(a << 1) * b` the shift stays on `a`, where the target has it. On a
67-instruction N64 routine (SN64 GCC 2.8.1, `-G0 -mips3 -O2`) this was the last step of an exact match (640 -> 0).

Children: each `A * 2^k * B` as `(A << k) * B`.
"""
import re

from .added_term_halfword import _opening
from .integer_repair_support import IDENT, NUMBER, edit, integer, view

FAMILY = 'shifted_factor_product'
FAMILIES = (FAMILY,)
LIMIT = 6
_PRODUCT = re.compile(rf'(?<!\*)\*\s*(?P<n>{NUMBER})\s*(?=\*(?!=))')


def _operand_start(clean, end, floor):
    """Where the primary expression ending at `end` starts (a name, member, call, subscript or bracket), else None."""
    text = clean[floor:end].rstrip()
    while text.endswith((')', ']')):
        if text.endswith(')'):
            opening = _opening(text, len(text) - 1)
        else:
            subscript = re.search(r'\[[^\[\]]*\]$', text)
            opening = subscript.start() if subscript else None
        if opening is None:
            return None
        before = text[:opening].rstrip()
        # a bracket of its own, not a call's or a subscript's: the operand starts here
        if not re.search(rf'(?:{IDENT}|[\])])$', before) or re.search(r'\b(?:return|sizeof)$', before):
            return floor + opening
        text = before
    word = re.search(rf'{IDENT}(?:\s*(?:\.|->)\s*{IDENT})*$', text)
    return floor + word.start() if word else None


def variants(source, name):
    part = view(source, name)
    if not part or part.body.count('*') < 2:
        return []
    out = []
    for hit in _PRODUCT.finditer(part.clean, part.opening, part.end):
        value = integer(hit['n'])
        if value < 2 or value & (value - 1):
            continue
        start = _operand_start(part.clean, hit.start(), part.opening + 1)
        if start is None:
            continue
        operand = source[start:hit.start()].rstrip()
        shifted = f'({operand} << {value.bit_length() - 1}) '
        out.append((FAMILY, edit(source, [(start, hit.end(), shifted)])))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}

"""m2c's pointer sums, `p = (i * 4) + base;`, as integer arithmetic in either order.

gcc 2.7.2 orders an `addu`'s operands by how it builds the sum: as pointer arithmetic the base came first,
`addu $s1, $s2, $v0`, where two N64 functions' loops had `addu $s1, $v0, $s2`. As
`p = (void *) (((i & 0xFFFF) * 4) + (s32) base);` both were exact (one needed it in both of its loops). The value is
the same; only the register order changes, which the judge settles. Offered for every such sum together and for each
alone, index first and base first.

A byte cast of the base, `p = (u8 *) arg1 + i * 5;` with `arg1` an integer, is the same sum: pointer arithmetic puts
the base first where the target's `addu $v1, $v1, $a1` has the index first (a 61-instruction N64 table fill, KMC GCC
2.7.2, 5 -> 0).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'integer_pointer_sum'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
BYTE_CAST = re.compile(r'\(\s*(?:u8|s8|char|unsigned char|signed char)\s*\*\s*\)\s*(' + IDENT + r')$')
ASSIGN = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<lhs>' + IDENT + r')\s*=\s*(?P<rhs>[^;{}]+);')


def _pointers(clean, span, opening, end):
    """Names declared as pointers in the function: parameters and locals."""
    signature = clean[span[0]:opening]
    names = set(re.findall(r'\*\s*(' + IDENT + r')\s*[,)]', signature))
    names |= set(re.findall(r'(?m)^[ \t]*[\w ]+?\*\s*(' + IDENT + r')\s*;', clean[opening:end]))
    return names


def _python_split_sum(rhs):
    """(left, right) of a top-level `a + b`, or None."""
    depth = 0
    for i, ch in enumerate(rhs):
        depth += (ch == '(') - (ch == ')')
        if depth == 0 and ch == '+' and rhs[i - 1:i] != '+' and rhs[i + 1:i + 2] not in '+=':
            left, right = rhs[:i].strip(), rhs[i + 1:].strip()
            return (left, right) if left and right and '+' not in right.replace('(', ' ').split()[0] else None
    return None


_split_sum = _python_split_sum
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split_sum(rhs):
        for i in _scan.top_offsets(rhs, '+', 1):
            if rhs[i - 1:i] != '+' and rhs[i + 1:i + 2] not in '+=':
                left, right = rhs[:i].strip(), rhs[i + 1:].strip()
                return (left, right) if left and right and '+' not in right.replace('(', ' ').split()[0] else None
        return None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    pointers = _pointers(clean, span, opening, end)
    sites = []
    for m in ASSIGN.finditer(clean, opening, end):
        if m['lhs'] not in pointers:
            continue
        parts = _split_sum(m['rhs'])
        if not parts:
            continue
        left, right = parts
        cast = BYTE_CAST.match(left)
        if cast and right not in pointers:  # `(u8 *) base + i * 5`: a byte sum, whatever the base's own type
            index, base = right, cast[1]
        elif right in pointers and left not in pointers:
            index, base = left, right
        elif left in pointers and right not in pointers:
            index, base = right, left
        else:
            continue
        if re.search(r'\b' + IDENT + r'\s*\(', index) or '"' in index:
            continue
        sites.append((m.start('rhs'), m.end('rhs'), index, base))
    if not sites:
        return []
    result = []

    def rewrite(chosen, index_first):
        text = source
        for start, stop, index, base in sorted(chosen, reverse=True):
            index_text = source[start:stop]
            index_src = index_text[:0] + index
            expr = f'({index_src}) + (s32) {base}' if index_first else f'(s32) {base} + ({index_src})'
            text = text[:start] + f'(void *) ({expr})' + text[stop:]
        return text
    choices = [sites] + ([[s] for s in sites] if len(sites) > 1 else [])
    for chosen in choices[:4]:
        for index_first in (True, False):
            text = rewrite(chosen, index_first)
            if text != source and text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:6]

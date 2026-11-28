"""`-p->y / 1.8f` as `-(f32) p->y / 1.8f`, and back: whether an integer is negated before or after it becomes a float.

`-x / K` with an integer `x` negates in a general register (`negu`) and then converts (`cvt.s.w`). A target that
converts first and negates the float (`cvt.s.w $f0, $f0; neg.s $f0, $f0`) was written with the cast inside the minus.
The two are the same value for every 16-bit field (a 32-bit `x` differs only at `INT_MIN`). A particle-quad builder
(SN GCC 2.8.1, `-G0 -mips3 -O2`, an N64 function; one function, 200 -> 0) had the cast form.

Offered for a unary minus on a name, member or element that is then multiplied or divided by a float literal, and the
other way round for `-(f32) x` / `(f32) -x`. A candidate rewrite; the judge decides.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'float_negation_cast_order'
FAMILIES = (FAMILY,)
LIMIT = 8
ACCESS = rf'{IDENT}(?:\s*(?:->|\.)\s*{IDENT}|\s*\[[^][;]*\])*'
UNARY = r'(?:(?<=[=(,?:+*/])|(?<=\breturn))(?P<space>\s*)'
FLOAT = r'(?:[0-9]+\.[0-9]*(?:[eE][-+]?[0-9]+)?[fF]?)'
PLAIN = re.compile(rf'{UNARY}-(?P<value>{ACCESS})(?=\s*[*/]\s*{FLOAT})')
INNER = re.compile(rf'{UNARY}-\s*\(\s*(?:f32|float)\s*\)\s*(?P<value>{ACCESS})')
OUTER = re.compile(rf'{UNARY}\(\s*(?:f32|float)\s*\)\s*-\s*(?P<value>{ACCESS})')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    cast = 'f32' if re.search(r'\bf32\b', clean) else 'float'
    edits = []
    for pattern, form in ((PLAIN, '-({cast}) {value}'), (INNER, '-{value}'), (OUTER, '-({cast}) {value}')):
        sites = []
        for hit in pattern.finditer(clean, part.opening, part.end):
            start = hit.end('space')
            value = source[hit.start('value'):hit.end('value')]
            sites.append((start, hit.end(), form.format(cast=cast, value=value)))
        if len(sites) > 1:
            edits.append(sites)
        edits += [[site] for site in sites]
    result = []
    for sites in edits:
        child = source
        for start, end, text in reversed(sites):
            child = child[:start] + text + child[end:]
        result.append((FAMILY, child))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 120}

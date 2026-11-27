"""A division or remainder by a constant that the target computes unsigned, written with an unsigned constant.

m2c prints `v = rand() % 1800;` where the callee's type is a guess (`s32`), and the compiler then divides signed: `mult`
by the magic number, an `sra`, and the `subu` of the dividend's sign. A target with `multu` and `srl` divided unsigned.
`% 1800U` makes the operation unsigned whatever the dividend is declared as, without touching a callee's prototype that
other functions share. On a 204-instruction KMC GCC 2.7.2 -O1 effect spawner the two sites of its repaired machine draft
judged 1685 -> 1386.

Only when the target's assembly has a `multu` or `divu`. All the constant divisions together first, then each alone;
the exact judge decides every child."""
import re

from .csource import _blank, find

FAMILY = 'unsigned_constant_divide'
FAMILIES = (FAMILY,)
LIMIT = 8
_UNSIGNED = re.compile(r'(?<![\w.])(?:multu|divu)\s+\$')
_DIVIDE = re.compile(r'(?<![/*])[/%]=?(?![/*])\s*(?P<k>0[xX][0-9a-fA-F]+|[1-9]\d*)(?![\w.])')


def _sites(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    sites = []
    for hit in _DIVIDE.finditer(clean, span[0], span[1]):
        value = int(hit['k'], 0)
        if value > 2 and value & (value - 1):  # (a power of two is a shift or a mask: another rewrite)
            sites.append(hit.end('k'))
    return sites


def _suffixed(source, ends):
    for end in sorted(ends, reverse=True):
        source = source[:end] + 'U' + source[end:]
    return source


def variants(source, name, asm=''):
    if not _UNSIGNED.search(asm or ''):
        return []
    sites = _sites(source, name)
    children = [_suffixed(source, sites)] if len(sites) > 1 else []
    children += [_suffixed(source, [site]) for site in sites]
    return [(FAMILY, child) for child in children[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}

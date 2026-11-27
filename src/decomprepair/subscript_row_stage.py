"""A table subscript's row product staged in a local inside the subscript: `T[(row = id * 0x110) + col]`.

`T[id * 0x110 + sel->col]` on KMC GCC 2.7.2 (N64, `-O1`) loads both bytes before the shifts that make the product; the
target shifts first and loads the column byte after. Naming the product (`T[(row = id * 0x110) + sel->col]`, one `s32`
local for every site) gives the target's order. Measured on a 174-instruction setup routine with four such
subscripts, three of them call arguments: 590 -> 0 with all sites together; the 2-D declaration, casts and operand
order of the same sum scored 590 or worse. Hypothesis (not confirmed in the compiler's source): the assignment forces
the product to be expanded to a register before the other operand is loaded.

Children, for each subscript `[ATOM * CONST + ATOM]` (either factor order): that site alone, then every site
together (one per statement, since two assignments of one local in a statement are unsequenced). Atoms are names
with `.`, `->` and simple `[..]`, no calls or side effects. MIPS only. The candidate is never a verdict.
"""
import re

from .csource import _blank, find

FAMILY = 'subscript_row_stage'
FAMILIES = (FAMILY,)
_LIMIT = 8
_ATOM = r'[A-Za-z_]\w*(?:(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)|\[\s*\w+\s*\])*'
_CONST = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
_SUBSCRIPT = re.compile(rf'\[\s*((?:{_ATOM}\s*\*\s*{_CONST})|(?:{_CONST}\s*\*\s*{_ATOM}))\s*\+\s*({_ATOM})\s*\]')


def _sites(clean, lo, hi):
    """[(product start, product end, statement start)] of the subscripts to stage, in order."""
    out = []
    for hit in _SUBSCRIPT.finditer(clean, lo, hi):
        statement = max(clean.rfind(c, lo, hit.start()) for c in ';{}')
        out.append((hit.start(1), hit.end(1), statement))
    return out[:_LIMIT]


def _apply(source, opening, sites, local):
    for start, end, _ in reversed(sites):
        source = f'{source[:start]}({local} = {source[start:end]}){source[end:]}'
    return f'{source[:opening + 1]}\n    s32 {local};{source[opening + 1:]}'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0 or re.search(r'\b(?:asm|__asm__)\b', clean[span[0]:span[1]]):
        return []
    sites = _sites(clean, opening, span[1])
    if not sites:
        return []
    local, number = 'row_term', 2
    while re.search(rf'\b{local}\b', source):
        local, number = f'row_term{number}', number + 1
    groups = [[site] for site in sites]
    together = list({site[2]: site for site in reversed(sites)}.values())[::-1]
    if len(together) > 1:
        groups.append(together)
    return [(FAMILY, _apply(source, opening, group, local)) for group in groups]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}

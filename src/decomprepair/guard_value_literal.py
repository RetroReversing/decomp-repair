"""A name read back inside the arm that tested it equal to a number, written as the number.

m2c names a register after what it last loaded. Under `if (gReady == 1)` the register that holds `gReady` is known to
hold 1, and the compiler stores it wherever the arm wants a 1, even after calls (it keeps the tested value in a saved
register). m2c writes that store as the global:

    if (gReady == 1) {                 if (gReady == 1) {
        if (find() == 5) {        ->       if (find() == 5) {
            gFull = (s32) gReady;              gFull = 1;

Written as the global, the compiler has to load it again after the call; written as the number, it reuses the register
that holds the tested value, as the target does.

Matched on an SN GCC 2.8.1 (`-G0 -mips3 -O2`) N64 save-space check (141 instructions): the last step, 215 -> 0.

guard_value_literal
    In the arm of `if (x == K)` (or the `else` arm of `if (x != K)`), every `y = x;` or `y = (T) x;` becomes `y = K;`.
    All such statements in one child, then each alone when there are several. Declined when the arm itself writes `x`
    or takes its address.

A hypothesis like every family's (a call in the arm may change a global, and then the register the compiler kept is the
number tested, not the global's new value); the judge decides.
"""
import re

from .csource import _blank, find
from .goto_structure_repairs import parse, walk
from .pattern_repairs import close

FAMILY = 'guard_value_literal'
FAMILIES = (FAMILY,)

MAX_SITES = 6
_ID = r'[A-Za-z_]\w*'
_TEST = re.compile(rf'\s*(?P<name>{_ID})\s*(?P<op>==|!=)\s*(?P<value>-?(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?)\s*')


def _sites(clean, opening, end):
    try:
        function = parse(clean, opening + 1, end - 1)
    except (ValueError, RecursionError):
        return []
    found = {}
    for s, _ in walk(function):
        if s.kind != 'if':
            continue
        test = _TEST.fullmatch(clean[s.parts['cond'][0]:s.parts['cond'][1]])
        if not test:
            continue
        part = s.parts['then'] if test['op'] == '==' else s.parts.get('other')
        if not part or not part['stmts']:
            continue
        name = test['name']
        a, b = part['stmts'][0].start, part['stmts'][-1].end
        arm = clean[a:b]
        if re.search(rf'(?<![\w.>]){name}\s*(?:\+\+|--|(?:<<|>>|[+*/%&|^\-])?=(?!=))|(?:\+\+|--)\s*{name}\b|'
                     rf'(?<!&)&\s*{name}\b', arm):
            continue
        copy = re.compile(rf'(?<![=!<>+\-*/%&|^])=\s*(?P<read>(?:\(\s*{_ID}\s*\**\s*\)\s*)?{name})\s*;')
        for hit in copy.finditer(arm):
            found.setdefault((a + hit.start('read'), a + hit.end('read')), test['value'])
    return sorted(found.items())[:MAX_SITES]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    sites = _sites(clean, opening, end)
    if not sites:
        return []

    def written(chosen):
        out = source
        for (a, b), value in reversed(chosen):
            out = out[:a] + value + out[b:]
        return out

    groups = [sites] + ([[site] for site in sites] if len(sites) > 1 else [])
    return [(FAMILY, written(group)) for group in groups]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

"""A global updated through m2c's temporary, written as the compound assignment it was.

m2c spells `v = G -= x;` as three statements, `t = G - x; v = t; G = t;` (a rewrite may leave them as `register`
declarations, which are new variables). gcc keeps `t` and `v` apart and stores a copy; the game computed once and
copied the result (`subu $v0`, `move $v1, $v0`, `sw $v0`). An N64 function was 94.5% so and exact as
`v = G -= x;` or `G -= x; v = G;`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'compound_global_update'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'
SHAPE = re.compile(r'(?m)^(?P<ind>[ \t]*)(?:register\s+)?(?P<t>' + I + r')\s*=\s*(?P<g>' + I + r')\s*(?P<op>[-+|&^])\s*(?P<x>[^;\n]+);[ \t]*\n'
                   r'(?:[ \t]*(?:register\s+)?(?P<v>' + I + r')\s*=\s*(?P=t)\s*;[ \t]*\n)?'
                   r'[ \t]*(?P=g)\s*=\s*(?P=t)\s*;[ \t]*\n')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for hit in SHAPE.finditer(clean, opening, end):
        t, g, op, v, ind = hit['t'], hit['g'], hit['op'], hit['v'], hit['ind']
        x = source[hit.start('x'):hit.end('x')].strip()
        rest = clean[hit.end():end]
        if re.search(r'\b' + t + r'\b', rest) or re.search(r'\b' + t + r'\b', x):
            continue
        forms = [f'{ind}{v} = {g} {op}= {x};\n', f'{ind}{g} {op}= {x};\n{ind}{v} = {g};\n'] if v else [f'{ind}{g} {op}= {x};\n']
        for form in forms:
            text = source[:hit.start()] + form + source[hit.end():]
            result.append((FAMILY, text))
    return result[:4]

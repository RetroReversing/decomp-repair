"""A float field advanced by a product, the product staged in one local the function shares between its updates.

m2c writes `F = F + (x * k);` for each of a function's float updates. When the updates sit in different basic blocks
(each follows a float-to-integer conversion's branch) and the game had a variable they all went through, the product is a
pseudo with sets in several blocks: GCC 2.7.2's local-alloc leaves it to global-alloc and never ties it to an operand of
the multiply. A product written in the expression is a block-local pseudo, which local-alloc ties to the multiply's
first operand that dies there, so the product takes the converted value's register where the target's takes the
constant's (`mul.s $f2,$f0,$f2` against `mul.s $f0,$f0,$f2`). Found by hand on a state machine's three table-driven float
updates (docs/learnings/function/identical-run-goto-state-machine-arms.md: 100 -> 60, the registers of six rows).

    a = a + tab[i] * 0.5f;                     prod = tab[i] * 0.5f;
    b = b + tab[j] * 0.25f;          ->        a = a + prod;
                                               prod = tab[j] * 0.25f;
                                               b = b + prod;

with `prod` one float local declared at the top of the function. The type is the float type written in the updated
field (`f32` or `f64`, `float` or `double`); at least two updates are needed, and every one of them is rewritten.
(Hypothesis, from local-alloc.c's `combine_regs`: a pseudo that has no quantity cannot be tied.)
"""
import re

from .csource import _blank, find

FAMILY = 'shared_product_local'
FAMILIES = (FAMILY,)

_UPDATE = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<lhs>[^\n;=!<>]*?[^\n;=!<>\s])[ \t]*=(?!=)[ \t]*(?P=lhs)[ \t]*\+[ \t]*'
    r'(?P<term>[^\n;]*\*[^\n;]*);[ \t]*\n')
_FLOAT = re.compile(r'\b(f32|f64|float|double)\b')
_NAME = 'shared_product'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0 or re.search(r'\b' + _NAME + r'\b', clean[span[0]:span[1]]):
        return []
    hits = []
    for hit in _UPDATE.finditer(clean, opening + 1, span[1]):
        kind = _FLOAT.search(hit['lhs'])
        if kind:
            hits.append((hit, kind[1]))
    if len(hits) < 2 or len({kind for _, kind in hits}) != 1:
        return []
    text = source
    for hit, _ in reversed(hits):
        indent = hit['indent']
        text = (text[:hit.start()] + f'{indent}{_NAME} = {hit["term"].strip()};\n' +
                f'{indent}{hit["lhs"].strip()} = {hit["lhs"].strip()} + {_NAME};\n' + text[hit.end():])
    line_end = text.index('\n', text.index('{', opening)) + 1
    text = text[:line_end] + f'  {hits[0][1]} {_NAME};\n' + text[line_end:]
    return [(FAMILY, text)] if text != source else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

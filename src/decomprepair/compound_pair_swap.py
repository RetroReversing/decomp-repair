"""A float built by an assignment and a compound assignment, with the two operands exchanged.

    t = (f32) count;                      t = p->rate;                    (or in one: t = p->rate * (f32) count;)
    t *= p->rate;             ->          t *= (f32) count;

The two statements decide which value is written straight into `t`'s register and which gets a temporary, and which
load comes first. `compound_operand_split` writes `t = a * b;` as two statements, but nothing exchanged a pair already
written that way: `commute_factor` swaps within one expression only. On an N64 envelope stepper (KMC GCC 2.7.2
`-G0 -mips3 -O2`, 119 instructions) three float rows were all that was left, with `$f0` and `$f2` exchanged: either
child scored 0 from 15 (one function; the register reason is a hypothesis, not read from the compiler's source).

For two adjacent statements `V = X; V *= Y;` (or `+=`) where `V` is a `float`/`f32` local or parameter, neither
operand mentions `V`, calls or assigns: the exchanged pair, and the one expression `V = Y * X;`. `V` converts either
operand to `float` and `*`/`+` commute, so the value is the same; a `double` anywhere in an operand, or an unsuffixed
floating literal, would not be and declines, as does a function with a `volatile`. One child of each form per pair,
and one with every pair exchanged. Only MIPS. The exact judge decides.
"""
import re

from .csource import _blank, find
from .integer_repair_support import edit

FAMILY = 'compound_pair_swap'
FAMILIES = (FAMILY,)
LIMIT = 24
_ID = r'[A-Za-z_]\w*'
_FLOATS = re.compile(r'\b(?:f32|float)\b(?!\s*\*)\s+([^;(){}]*)(?=[;),])')
_PAIR = re.compile(rf'(?<=[;{{}}:])(?P<lead>\s*)(?P<v>{_ID})\s*=(?!=)\s*(?P<x>[^;{{}}]+?);(?P<gap>\s*)(?P=v)\s*'
                   r'(?P<op>[*+])=\s*(?P<y>[^;{}]+?);')
_UNSAFE = re.compile(rf'\b(?:double|f64)\b|(?<!sizeof){_ID}\s*\(|\+\+|--|(?<![=!<>])=(?!=)|[?,]|'
                     r'(?<![\w.])\d+\.\d*(?:[eE][+-]?\d+)?(?![\w.])')


def _declared(text):
    return {part.split('=')[0].strip() for hit in _FLOATS.finditer(text) for part in hit[1].split(',')
            if re.fullmatch(_ID, part.split('=')[0].strip())}


def _paren(text):
    return text if re.fullmatch(r'[\w.]+', text) else f'({text})'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    if re.search(r'\bvolatile\b', clean[span[0]:span[1]]):
        return []
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    floats = _declared(clean[span[0]:span[1]])
    pairs, joined = [], []
    for hit in _PAIR.finditer(clean, opening, span[1]):
        name_, op = hit['v'], hit['op']
        operands = (hit['x'], hit['y'])
        if name_ not in floats or any(_UNSAFE.search(item) or re.search(rf'(?<![\w.>]){name_}\b', item)
                                      for item in operands):
            continue
        x = source[hit.start('x'):hit.end('x')].strip()
        y = source[hit.start('y'):hit.end('y')].strip()
        pairs.append((hit.start('v'), hit.end(), f'{name_} = {y};{hit["gap"]}{name_} {op}= {x};'))
        joined.append((hit.start('v'), hit.end(), f'{name_} = {_paren(y)} {op} {_paren(x)};'))
    out = [(FAMILY, edit(source, [item])) for item in pairs]
    out += [(FAMILY, edit(source, [item])) for item in joined]
    if len(pairs) > 1:
        out.insert(0, (FAMILY, edit(source, pairs)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}

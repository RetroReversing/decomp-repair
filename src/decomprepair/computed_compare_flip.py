"""A comparison between a computed value and a load, written the other way round; and `x += v` as `x = v + x`.

gcc 2.7.2 evaluates the first operand first, so `limit - 2 < p[4]` and `p[4] > limit - 2` take their registers and
order differently, and so do `p[4] += d` and `p[4] = d + p[4]` (which register the sum lands in). `comparison_sides`
only swaps two loads. Each took the last rows of a 76-instruction KMC `-O1` easing routine (80 to 20 to 0).

Only side-effect free operands: a name and a literal offset against an element, field or dereference of a name; an
added value with no call or assignment in it.
"""
import re

from .arm_block_support import IDENT
from .integer_repair_support import NUMBER, edit, view

COMPARE = 'computed_compare_flip'
ADD = 'compound_value_first'
FAMILIES = (COMPARE, ADD)

FLIP = {'<': '>', '>': '<', '<=': '>=', '>=': '<=', '==': '==', '!=': '!='}
LOAD = rf'{IDENT}(?:\s*\[\s*(?:{NUMBER}|{IDENT})\s*\]|\s*->\s*{IDENT})'
COMPUTED = rf'{IDENT}\s*[-+]\s*{NUMBER}'
ORDER = r'(?P<op><=|>=|==|!=|<|>)'
EDGE = r'(?<=[(&|])\s*'
CLOSE = r'(?=\s*(?:\)|&&|\|\|))'
COMPARISONS = (re.compile(rf'{EDGE}(?P<a>{COMPUTED})\s*{ORDER}\s*(?P<b>{LOAD}){CLOSE}'),
               re.compile(rf'{EDGE}(?P<a>{LOAD})\s*{ORDER}\s*(?P<b>{COMPUTED}){CLOSE}'))
COMPOUND = re.compile(rf'(?<=[;{{}}])\s*(?P<lv>{LOAD}|\*\s*{IDENT})\s*\+=\s*(?P<value>[^;{{}}]+);')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    out = []

    def emit(family, groups):
        for edits in groups[:6]:
            text = edit(source, edits)
            if (family, text) not in out:
                out.append((family, text))
        if len(groups) > 1:
            text = edit(source, [one for group in groups for one in group])
            if (family, text) not in out:
                out.append((family, text))

    flips = []
    for pattern in COMPARISONS:
        for hit in pattern.finditer(body):
            at = part.opening
            flips.append([(at + hit.start('a'), at + hit.end('b'),
                           f'{source[at + hit.start("b"):at + hit.end("b")]} {FLIP[hit["op"]]} '
                           f'{source[at + hit.start("a"):at + hit.end("a")]}')])
    emit(COMPARE, flips)
    sums = []
    for hit in COMPOUND.finditer(body):
        value = hit['value'].strip()
        if re.search(r'\+\+|--|(?<![=!<>])=(?!=)|\b(?!(?:s8|u8|s16|u16|s32|u32|f32|int|short|char|float)\b)'
                     + IDENT + r'\s*\(', value):
            continue
        at = part.opening
        target = source[at + hit.start('lv'):at + hit.end('lv')]
        written = source[at + hit.start('value'):at + hit.end('value')].strip()
        if re.search(r'[-+*/%<>&|^?:]\s', re.sub(r'\([^()]*(?:\([^()]*\))*[^()]*\)', '', value) + ' '):
            written = f'({written})'
        sums.append([(at + hit.start('lv'), at + hit.end(0), f'{target} = {written} + {target};')])
    emit(ADD, sums)
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 92}  # the registry: no caller wiring (registry.py)

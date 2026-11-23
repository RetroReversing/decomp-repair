"""A literal held in a local and stored through several statements, written as one chained assignment.

m2c, and a search that copies it, writes `zero = 0.0f;` once and then `p->z = zero; p->y = zero; p->x = zero;`; the
original had `p->x = p->y = p->z = 0.0f;`. GCC 2.7.2 keeps the literal of a chained assignment in one pseudo that the
stores read in order (`mtc1 $zero, $f0; swc1 $f0, 0x2c($s0); swc1 $f0, 0x28($s0); ...`), while a local the search spelled
out (often inside a `do { } while (0);` fence that raised its weight) lives as long as the statements around it: the
target's float registers came out swapped (the zeroing pseudo in `$f2`, the third coordinate in `$f0`), and the literal
sat on the wrong side of the load it was set beside. On a 603-instruction N64 state machine, the chained form with the
fence taken off took the vector save from 415 to 285: all the float register rows of that arm, and the first step toward
the match.

A proposal needs `NAME = LITERAL;` (a float or integer literal, NAME a local), then two or more consecutive statements
`LVALUE = NAME;` after it (a `} while (0);` fence may close in between), and NAME read nowhere else. The stores run in
their order (`A3 = A2 = A1 = LITERAL;` runs A1 first). Labelled `float_literal_chain`: the chain with the fence left where
it was; and, when the fence held only one other statement, the chain with the fence taken off.
"""
import re

from .csource import _blank, find

FAMILY = 'float_literal_chain'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_LITERAL = r'[-+]?(?:\d+\.\d*(?:[eE][-+]?\d+)?[fF]?|\d+[fF]|0[xX][0-9A-Fa-f]+|\d+)'
_TYPES = r'(?:f32|float|f64|double|s32|u32|int|unsigned int|s16|u16|s8|u8)'
_ASSIGN = re.compile(rf'(?<![\w.>])({_ID}) = ({_LITERAL});')
_FENCE_CLOSE = re.compile(r'\s*\}\s*while \(0\);')
_STORE = re.compile(r'\s*([^;{}=\n!<>][^;{}\n]*?[^;{}=\s!<>])\s*=\s*(' + _ID + r')\s*;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    out = []
    for m in _ASSIGN.finditer(clean, opening, closing):
        local, literal = m[1], m[2]
        if not re.search(rf'(?m)^\s*{_TYPES}\s+{local}\s*;', clean[opening:closing]):
            continue
        at = m.end()
        fence = _FENCE_CLOSE.match(clean, at)
        if fence:
            at = fence.end()
        stores = []
        while True:
            store = _STORE.match(clean, at)
            if not store or store[2] != local or re.search(r'\bif\b|\breturn\b|\bwhile\b', store[1]):
                break
            stores.append((store.start(), store.end(), store[1].strip()))
            at = store.end()
        if len(stores) < 2:
            continue
        end = stores[-1][1]
        if re.search(rf'\b{local}\b', clean[end:closing]):
            continue
        inside = clean[m.end():stores[0][0]]
        if re.search(rf'\b{local}\b', inside):
            continue
        chain = ' = '.join([lv for _, _, lv in reversed(stores)] + [literal]) + ';'
        first = m.start()
        while first > 0 and source[first - 1] in ' \t':
            first -= 1
        gap = source[m.end():stores[0][0]]
        lead = source[stores[0][0]:stores[0][1]]
        lead = lead[:len(lead) - len(lead.lstrip())]
        out.append((FAMILY, source[:first] + gap + lead + chain + source[end:]))
        if fence:
            head = clean[:m.start()]
            opener = re.search(r'(?s)\bdo\s*\{\s*((?:[^;{}]*;)\s*)\Z', head)
            if opener and clean[opener.start(1):m.start()].count(';') == 1:
                inner = source[opener.start(1):m.start()].strip()
                begin = opener.start()
                while begin > 0 and source[begin - 1] in ' \t':
                    begin -= 1
                text = source[:begin] + f'{inner}{lead}{chain}' + source[end:]
                out.append((FAMILY, text))
    seen, unique = set(), []
    for item in out:
        if item[1] != source and item[1] not in seen:
            seen.add(item[1])
            unique.append(item)
    return unique


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)

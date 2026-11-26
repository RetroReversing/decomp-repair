"""A pointer local that only ever names one symbol, written as the array that symbol was.

A search keeps `u8 *q = &D_x;` beside `extern u8 D_x;` and reads `q[0]`, `q[-1]`, `q + 0xDE`. Set at the top, the local
is a value the whole function carries, so its address is loaded before the dispatch. With `extern u8 D_x[];` and the
symbol written at each use, gcc 2.7.2 -O1 loads the address where the first use is and keeps it for that block only
(420 -> 0 on a 148-instruction state machine, together with `scaffold_strip`'s plain form; neither alone moves it).
Offered for a local of the extern's own element type that is set once to the symbol's address, as the source stands and
on its stripped form.
"""
import re

from . import scaffold_strip
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'symbol_alias_array'
FAMILIES = (FAMILY,)
LIMIT = 8

I = r'[A-Za-z_]\w*'
ALIAS = re.compile(r'(?m)^[ \t]*(?P<type>' + I + r')\s*\*\s*(?P<local>' + I + r')\s*=\s*&\s*(?P<symbol>' + I + r')\s*;[ \t]*\n')


def variants(source, name):
    result = [(FAMILY, text) for text in _inlined(source, name)]
    stripped = scaffold_strip.plain(source, name)
    if stripped and stripped != source:
        result += [(FAMILY, text) for text in _inlined(stripped, name)]
    return result[:LIMIT]


def _inlined(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for hit in ALIAS.finditer(clean, opening, end):
        local, symbol, kind = hit['local'], hit['symbol'], hit['type']
        declared = re.search(r'(?m)^[ \t]*extern\s+' + kind + r'\s+(' + symbol + r')\s*;', clean[:span[0]])
        if not declared:
            continue
        rest = clean[opening:hit.start()] + clean[hit.end():end]
        if re.search(r'(?<![\w.>])' + local + r'\s*(?:=(?!=)|\+\+|--|[-+&|^]=)|(?:\+\+|--|&)\s*' + local + r'\b', rest):
            continue
        # elsewhere in the file the symbol must be this function's alone to retype
        outside = clean[:declared.start()] + clean[declared.end():span[0]] + clean[end + 1:]
        if re.search(r'\b' + symbol + r'\b', outside):
            continue
        body = source[opening:hit.start()] + source[hit.end():end]
        body = re.sub(r'(?<![\w.>&])' + symbol + r'\b', symbol + '[0]', body)
        body = re.sub(r'&\s*' + symbol + r'\b', symbol, body)
        body = re.sub(r'(?<![\w.>])' + local + r'\b', symbol, body)
        head = source[:declared.end(1)] + '[]' + source[declared.end(1):opening]
        result.append(head + body + source[end:])
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 120}

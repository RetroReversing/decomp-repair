"""A global m2c declared as one value and indexed through its own address, declared as the array it is.

m2c saw a table of pointers and typed it as one pointer, then reaches the other entries through its address:

    extern u8 **D_80001000;                 extern u8 **D_80001000[];
    first = D_80001000;                ->   first = D_80001000[0];
    list = (&D_80001000)[page];             list = D_80001000[page];

Both read the same words, but GCC builds `(&D)[i]` as an address taken first and added to the scaled index, while the
declared array builds the index first and the symbol's `lui` after it, in the other registers. Only when the function
indexes the address at least once and takes it nowhere else, and the source declares the symbol; every plain use becomes
`D[0]`. One child with every such global. On a 461-instruction N64 menu screen (SN64 GCC 2.8.1) it was the last 210
points: eleven register rows.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'address_indexed_global'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
DECLARED = re.compile(rf'(?m)^[ \t]*extern[ \t]+(?P<type>{IDENT}(?:[ \t]+{IDENT})?[ \t]*\**)[ \t]*(?<![\w])(?P<name>{IDENT})'
                      r'(?P<end>[ \t]*;)')
TAKEN = re.compile(rf'\(\s*&\s*(?P<name>{IDENT})\s*\)\s*(?=\[)')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    indexed = {}
    for hit in TAKEN.finditer(clean, opening, end):
        indexed.setdefault(hit['name'], []).append(hit)
    if not indexed:
        return []
    edits = []
    for declared in DECLARED.finditer(clean):
        symbol = declared['name']
        if symbol not in indexed or opening <= declared.start() < end:
            continue
        word = re.compile(rf'(?<![\w.>])(?<!->){symbol}(?!\w)')
        taken = {hit.start('name'): hit for hit in indexed[symbol]}
        outside = [use.start() for use in word.finditer(clean)
                   if not opening <= use.start() < end and use.start() != declared.start('name')]
        plain = [use for use in word.finditer(clean, opening, end) if use.start() not in taken]
        if outside or any(clean[:use.start()].rstrip().endswith('&') and not clean[:use.start()].rstrip().endswith('&&')
                          for use in plain):
            continue
        edits.append((declared.start('end'), declared.start('end'), '[]'))
        edits += [(hit.start(), hit.end(), symbol) for hit in taken.values()]
        edits += [(use.end(), use.end(), '[0]') for use in plain]
    if not edits:
        return []
    text = source
    for start, stop, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[stop:]
    return [(FAMILY, text)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

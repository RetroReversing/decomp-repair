"""A table m2c stores through its symbol's address, field by field, declared as the array it is.

m2c, which knows a table only by its address, writes `M2C_FIELD(&D_800FA198, M2C_UNK **, 4) = p;`: a load or store
through `(s8 *)&D_800FA198 + 4`. cse treats that as the base plus a constant and the compiler shares one register for
the base across a run of stores, or folds the offset into a `%lo(sym+4)` of its own. Written as `D_800FA198[1] = p;`
over `extern M2C_UNK *D_800FA198[];` the addressing is the array's: a state initialiser that fills a table of 21
pointers went from 1510 to 740 with only this change (SN GCC 2.8.1 -O2, 205 instructions), and the rest was
`store_tail_into_arms` (740 -> 0).

`variants` takes each symbol declared `extern T name;` whose every use is `&name` and whose `M2C_FIELD(&name, E *, K)`
accesses (three or more distinct offsets) share one element type E of a known size with K a multiple of it, redeclares
it `extern E name[];` and writes the accesses as `name[K / size]`. A symbol read by its bare name, or accessed with two
element types, is left alone. One child per symbol, and one with all of them. A candidate rewrite; the judge decides.
"""
import re

from .csource import _blank, find

FAMILY = 'symbol_field_array'
FAMILIES = (FAMILY,)
LIMIT = 8
MINIMUM = 3

_IDENT = r'[A-Za-z_]\w*'
_FIELD = re.compile(rf'\bM2C_FIELD\s*\(\s*&\s*(?P<sym>{_IDENT})\s*,\s*(?P<elem>{_IDENT}(?:\s+{_IDENT})?[\s*]*?)\s*\*\s*,'
                    r'\s*(?P<k>0[xX][0-9a-fA-F]+|\d+)\s*\)')
_SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'long': 4,
          'f32': 4, 'float': 4, 'M2C_UNK': 4, 'M2C_UNK8': 1, 'M2C_UNK16': 2, 'M2C_UNK32': 4, 's64': 8, 'u64': 8,
          'f64': 8, 'double': 8}


def _size(element):
    if element.endswith('*'):
        return 4
    return _SIZES.get(element.split()[-1])


def _tables(source, clean, span):
    """{symbol: (element type, size, declaration match, [access matches])} for the symbols that qualify."""
    hits = {}
    for hit in _FIELD.finditer(clean, span[0], span[1]):
        hits.setdefault(hit['sym'], []).append(hit)
    found = {}
    for symbol, accesses in hits.items():
        elements = {re.sub(r'\s*\*', ' *', ' '.join(a['elem'].split())).replace('* *', '**') for a in accesses}
        if len(elements) != 1:
            continue
        element = elements.pop()
        size = _size(element)
        offsets = {int(a['k'], 0) for a in accesses}
        if not size or len(offsets) < MINIMUM or any(k % size for k in offsets):
            continue
        declaration = re.search(rf'(?m)^[ \t]*extern\s+(?P<type>{_IDENT}[\s*]*?)\b{symbol}\s*;(?:[ \t]*/\*[^\n]*?\*/)?',
                                clean)
        if not declaration:
            continue
        # every other use must take the address: a bare read of the name would change meaning once it is an array
        uses = [m for m in re.finditer(rf'\b{symbol}\b', clean)
                if not declaration.start() <= m.start() < declaration.end()]
        if any(not clean[:m.start()].rstrip().endswith('&') or re.match(r'\s*(?:\.|->|\[)', clean[m.end():])
               for m in uses):
            continue
        found[symbol] = (element, size, declaration, accesses)
    return found


def _apply(source, tables, symbols):
    edits = []
    for symbol in symbols:
        element, size, declaration, accesses = tables[symbol]
        space = '' if element.endswith('*') else ' '
        start = declaration.start() + len(declaration[0]) - len(declaration[0].lstrip())
        end = source.index(';', start) + 1
        edits.append((start, end, f'extern {element}{space}{symbol}[];'))
        edits.extend((a.start(), a.end(), f'{symbol}[{int(a["k"], 0) // size}]') for a in accesses)
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    tables = _tables(source, _blank(source), span)
    chosen = sorted(tables, key=lambda s: -len(tables[s][3]))[:LIMIT]
    groups = [[symbol] for symbol in chosen]
    if len(chosen) > 1:
        groups.insert(0, chosen)
    return [(FAMILY, _apply(source, tables, group)) for group in groups]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

"""Scalar globals declared as unsized arrays, and their near neighbours addressed from them.

GCC 2.7 (KMC, `-G0 -mips3 -O1`) folds `extern u16 flags;` into `lui; lhu %lo(flags)` at every access. A target that
builds the address once with `lui $reg; addiu $reg, %lo(...)` and reads `0($reg)`, and reaches nearby globals as
`-8($reg)`, `-0x10($reg)`, was written with a type the compiler cannot fold: an array of unknown size, with the
neighbours addressed from it (they are fields or elements of one object in the original source; that is a hypothesis,
the bytes are what is measured).

Measured on a 141-instruction N64 function (a menu state handler): scalar externs 6301, the three flag globals as
unsized arrays 1980, then the neighbours read from those arrays, 0. m2c writes every global as its own scalar.

Two families:

- `unsized_extern_array`: one child per referenced `extern TYPE D_x;` scalar declared `extern TYPE D_x[];` and read as
  `D_x[0]`, and one with all of them;
- `neighbour_symbol_rebase`: one child per reference to a scalar `D_x` whose address is within 0x40 bytes of an
  unsized array `D_y`, rewritten `*(TYPE *)((char *)D_y - K)` (one reference at a time: a target often rebases only
  some of them), one with every reference of one symbol, and each run of two or three neighbouring references (a
  137-instruction N64 menu handler, `-O1`: the test and the decrement of one block reached the byte as `-0x2c($s0)` off a
  neighbouring array held in `$s0`, the later blocks by its own name; 991 -> 10, then `initializer_placement` -> 0).

The program reads and writes the same addresses: the offsets come from the symbols' own names."""
import re

from .csource import _blank
from .integer_repair_support import view

UNSIZED = 'unsized_extern_array'
REBASE = 'neighbour_symbol_rebase'
FAMILIES = (UNSIZED, REBASE)
REACH = 0x40
LIMIT = 90
RUN = 3  # the longest run of references rebased together
SCALAR = r'(?:(?:volatile|unsigned|signed)\s+)*(?:char|short|int|long|float|double|[su](?:8|16|32|64)|f(?:32|64))'
_DECL = re.compile(rf'^[ \t]*extern[ \t]+(?P<type>{SCALAR})[ \t]+(?P<name>D_(?P<at>[0-9A-Fa-f]{{8}}))[ \t]*(?P<array>\[[^\]\n]*\])?[ \t]*;', re.M)


def _declarations(source):
    return {hit['name']: hit for hit in _DECL.finditer(_blank(source))}


def _references(part, name):
    return [(part.opening + 1 + hit.start(), part.opening + 1 + hit.end())
            for hit in re.finditer(rf'(?<![\w.>])(?<![\w\]\)]&)(?<!&){name}\b', part.body)]


def _edit(source, edits):
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def _unsized(source, part, declared):
    singles = []
    for symbol, hit in declared.items():
        if hit['array'] is not None:
            continue
        places = _references(part, symbol)
        # `&symbol` would change type; a reference elsewhere in the file would not compile as an array
        if not places or re.search(rf'&\s*{symbol}\b', part.body) or len(_references(part, symbol)) != len(
                re.findall(rf'\b{symbol}\b', part.body)):
            continue
        if len(re.findall(rf'\b{symbol}\b', _blank(source))) != len(places) + 1:
            continue
        edits = [(hit.end('name'), hit.end('name'), '[]')] + [(start, end, f'{symbol}[0]') for start, end in places]
        singles.append(edits)
    children = [_edit(source, edits) for edits in singles]
    if len(singles) > 1:
        children.append(_edit(source, [edit for edits in singles for edit in edits]))
    return [(UNSIZED, child) for child in children]


def _rebased(source, part, declared):
    arrays = [hit for hit in declared.values() if hit['array'] is not None and re.search(rf'\b{hit["name"]}\b', part.body)]
    results, runs = [], []
    for symbol, hit in declared.items():
        if hit['array'] is not None and hit['array'].strip('[] \t') != '':
            continue
        unsized = hit['array'] is not None
        pattern = rf'(?<![\w.>&]){symbol}\s*\[\s*0\s*\]' if unsized else None
        places = ([(part.opening + 1 + m.start(), part.opening + 1 + m.end()) for m in re.finditer(pattern, part.body)]
                  if unsized else _references(part, symbol))
        if not places:
            continue
        near = [other for other in arrays if other['name'] != symbol
                and 0 < abs(int(other['at'], 16) - int(hit['at'], 16)) <= REACH]
        for other in sorted(near, key=lambda o: abs(int(o['at'], 16) - int(hit['at'], 16))):
            distance = int(hit['at'], 16) - int(other['at'], 16)
            sign = '+' if distance > 0 else '-'
            text = f'(*({hit["type"]} *)((char *){other["name"]} {sign} {abs(distance):#x}))'
            for start, end in places:
                results.append((REBASE, _edit(source, [(start, end, text)])))
            if len(places) > 1:
                results.append((REBASE, _edit(source, [(start, end, text) for start, end in places])))
            # a run of neighbouring references: one block reaches the object through the base, the rest by name
            for size in range(2, min(len(places), RUN + 1)):
                for first in range(len(places) - size + 1):
                    runs.append((REBASE, _edit(source, [(start, end, text) for start, end in places[first:first + size]])))
    return results + runs


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    declared = _declarations(source)
    results = _unsized(source, part, declared) + _rebased(source, part, declared)
    seen, out = {source}, []
    for family, text in results:
        if text not in seen:
            seen.add(text)
            out.append((family, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}

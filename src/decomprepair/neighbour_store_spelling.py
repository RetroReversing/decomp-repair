"""One store of a global spelled through its neighbour, so that two branch ends stay apart.

gcc's jump2 merges two branch ends whose last instructions are the same. Where the target keeps both copies of a pair
of stores (`D_x23 = v; D_x22 = 0;` in two arms), writing one arm's store as `(&D_x22)[1] = v;` names the same byte
through another `symbol_ref`, so the two instructions no longer compare equal while the linked bytes do. A KMC GCC
2.7.2 menu function (`-G0 -mips3 -mgp32 -mfp32 -O1`, a four-way `if` chain, each arm ending in two byte stores) merged
two arms the target kept: 810 -> 0 with one store respelled. The cross-jumping explanation is read from the output (the
merged tail and its jump), not confirmed in jump.c: a hypothesis.

`variants` takes each plain statement `D_x = value;` of a scalar declared `extern T D_x;` and offers it as
`(&D_y)[k] = value;` for each other global of the same type that the function stores, a whole number of elements and at
most 0x10 bytes away. Only names that say their address (`D_xxxxxxxx`) take part."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'neighbour_store_spelling'
FAMILIES = (FAMILY,)
LIMIT = 48
REACH = 0x10
_SIZES = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 'int': 4, 'float': 4}
_EXTERN = re.compile(rf'(?m)^[ \t]*extern[ \t]+(?P<type>{IDENT})[ \t]+(?P<name>D_[0-9A-Fa-f]{{8}})[ \t]*;')
_STORE = re.compile(r'(?<![\w\].>*&])(?P<name>D_[0-9A-Fa-f]{8})[ \t]*=(?!=)[^;={}]+;')


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    declared = {}
    for text in (re.sub(r'/\*.*?\*/|//[^\n]*', '', header or '', flags=re.S), part.clean[:part.opening]):
        for hit in _EXTERN.finditer(text):
            if hit['type'] in _SIZES:
                declared[hit['name']] = hit['type']
    stores = []
    for hit in _STORE.finditer(part.clean, part.opening, part.end):
        if hit['name'] in declared and part.clean[:hit.start()].rstrip()[-1:] in (';', '{', '}', ')', ':'):
            stores.append((hit['name'], hit.start('name'), hit.end('name')))
    stored = list(dict.fromkeys(symbol for symbol, _, _ in stores))
    result = []
    # the last arm is the one jump2 keeps as written, so earlier stores are the ones to respell: source order
    for symbol, start, end in stores:
        size = _SIZES[declared[symbol]]
        for other in stored:
            offset = int(symbol[2:], 16) - int(other[2:], 16)
            if other == symbol or declared[other] != declared[symbol] or offset % size or not 0 < abs(offset) <= REACH:
                continue
            result.append((abs(offset), len(result), (FAMILY, edit(source, [(start, end, f'(&{other})[{offset // size}]')]))))
    # nearest neighbour first
    return [child for _, _, child in sorted(result, key=lambda r: r[:2])][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}

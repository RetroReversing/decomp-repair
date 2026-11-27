"""A store whose value is the address of a word global, where the game stored the global's value.

m2c reads a word global as `D_800B2FE0` and a global it only sees an address of as `&D_800B2FE0`. When a draft (a
saved best, or an earlier repair that took addresses for values) stores that address,

    *(s32 *)(D_802028E0 + off) = (s32)&D_800B2FE0;

gcc builds the address (`lui; addiu %lo(D_800B2FE0)`) where the target loads the word (`lui; lw %lo(D_800B2FE0)`) and
stores it. A linked free-list push on a KMC GCC 2.7.2 N64 object allocator (`-G0 -mips3 -mgp32 -mfp32 -O2`): the node's
`next` field takes the list head's value; written with `&` the one `addiu` differed from the target's `lw`.
Written `= D_800B2FE0;` it matched. The reverse spelling, a value read where the code took the address, is
`global_value_address` in global_array_repairs.

Offered for `LV = &S;` and `LV = (T)&S;` (T a word integer type) when the source or header declares `extern T S;` for a
word scalar T (`s32`, `u32`, `int`, `unsigned int`, `M2C_UNK`): one child per such statement and one with all of them. An
array (`S[]`), a pointer or a byte or halfword global is never rewritten: its address is the value.

stored_address_value_read
    The rewrite above.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'stored_address_value_read'
FAMILIES = (FAMILY,)
LIMIT = 6
_WORD = r'(?:s32|u32|int|unsigned\s+int|M2C_UNK|M2C_UNK32)'
_STORE = re.compile(rf'(?<![=!<>+\-*/%&|^])=(?!=)\s*(?P<rhs>(?:\(\s*{_WORD}\s*\)\s*)?&\s*(?P<s>{IDENT}))\s*;')


def _is_word(source, header, symbol):
    return re.search(rf'\bextern\s+{_WORD}\s+{re.escape(symbol)}\s*;', source + '\n' + header) is not None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    edits = []
    for hit in _STORE.finditer(part.clean, part.opening + 1, part.end):
        symbol = hit['s']
        if not _is_word(source, header, symbol):
            continue
        # the left side must be a store target, not a declaration's initializer of a word that names the symbol
        line_start = max(part.clean.rfind(c, 0, hit.start()) for c in ';{}') + 1
        if re.search(rf'\b{re.escape(symbol)}\b', part.clean[line_start:hit.start()]):
            continue
        edits.append((hit.start('rhs'), hit.end('rhs'), symbol))
    children = [(FAMILY, edit(source, [e])) for e in edits[:LIMIT]]
    if len(edits) > 1:
        children.append((FAMILY, edit(source, edits)))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}

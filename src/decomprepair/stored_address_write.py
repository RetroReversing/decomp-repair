"""A global written right after its address was stored somewhere, written through the stored pointer.

m2c names a symbol directly where the game wrote it through the pointer it had just stored:

    slots[id].data = &D_801D59B2;
    D_801D59B2 = 0;

gcc then addresses the symbol with its own `lui`/`sb %lo` pair, where the game wrote `sb $zero, 0($v1)` through the
register that holds the address it stored. Written as `*(s8 *) slots[id].data = 0;` the value cse reads back is the one
just stored, and the store goes through that register. On a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O1`) object setup
routine this was the last row of the machine draft's chain after its record array: 250 -> 0.

Offered for `LV = &S; S = V;` (two adjacent statements, LV a name, member or index expression that does not name S) when
the source or header declares `extern T S;` with a scalar T; one child for each such pair and one with all of them.

stored_address_write
    The rewrite above.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'stored_address_write'
FAMILIES = (FAMILY,)
LIMIT = 6
_SCALAR = r'(?:unsigned\s+(?:char|short|int)|signed\s+char|s8|u8|s16|u16|s32|u32|f32|f64|char|short|int|float|double)'
_LVALUE = rf'{IDENT}(?:\s*(?:\.|->)\s*{IDENT}|\s*\[[^\[\]{{}};=]*\])*'
_PAIR = re.compile(rf'(?<![\w.>\]])(?P<lv>{_LVALUE})\s*=\s*&\s*(?P<s>{IDENT})\s*;\s*(?P<w>(?P=s))\s*=(?!=)')


def _type(source, header, symbol):
    hit = re.search(rf'\bextern\s+(?:volatile\s+)?({_SCALAR})\s+{re.escape(symbol)}\s*;', source + '\n' + header)
    return hit.group(1) if hit else None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    edits = []
    for hit in _PAIR.finditer(part.clean, part.opening + 1, part.end):
        symbol, lvalue = hit['s'], source[hit.start('lv'):hit.end('lv')]
        kind = _type(source, header, symbol)
        if not kind or re.search(rf'\b{re.escape(symbol)}\b', lvalue):
            continue
        edits.append((hit.start('w'), hit.end('w'), f'*({kind} *) {lvalue}'))
    children = [(FAMILY, edit(source, [e])) for e in edits[:LIMIT]]
    if len(edits) > 1:
        children.append((FAMILY, edit(source, edits)))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}

"""Scalars that sit inside a block the function clears, written as the elements of that block's array.

    memset(&D_80112E98, 0, 0x24);  ...  D_80112E9C = 1;  *(s32 *)((char *)&D_80112EB0 - 0x10) = 1;  D_80112EAC = 1;

The splitter names every address a game's code touches, so the words of one cleared block turn up as unrelated
scalars (`D_80112E9C`, `D_80112EA0`, `D_80112EAC`) and as `(char *)&D_80112EB0 - 0x10` casts, and nothing says they are
one array. The game indexed one array (`D_80112E98[1] = 1;`). The difference is not cosmetic: the forms of one symbol
share the address register the loop pass hoists (`addiu $t3,..; addiu $t7,$t3,-0x10`), the scalars and casts of
different symbols do not, so the hoisted registers, and with them every temporary the register allocator picks later,
differ. A 417-instruction input handler went 4236 -> 3145 with this one change (the hoisted address registers were then
the target's) and the rest of its register rows followed.

Offered when a function calls `memset(&D_X, 0, K)` (or `D_X`) on an address-named symbol and uses other names or casts
whose addresses fall inside `[X, X + K)`, 4-byte aligned, of a 4-byte type. Every such use becomes `D_X[k]` in one child
(a part of them is worse: the forms that stay scalar split the hoisted registers again), and the base's `extern` becomes
an array. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import NUMBER, edit, view

FAMILY = 'symbol_run_array'
FAMILIES = (FAMILY,)
WORD = r'(?:s32|u32|int|unsigned int|unsigned|long|unsigned long|vs32|vu32)'
_CLEAR = re.compile(rf'\bmemset\s*\(\s*(?:\(\s*void\s*\*\s*\)\s*)?(?P<amp>&\s*)?(?P<sym>D_(?P<addr>[0-9A-Fa-f]{{8}}))\s*,\s*0\s*,\s*(?P<len>{NUMBER})\s*\)')
_CAST = re.compile(
    rf'\*\s*\(\s*\(\s*{WORD}\s*\*\s*\)\s*\(*\s*\(\s*(?:char|u8|s8|unsigned char)\s*\*\s*\)\s*\(*\s*&\s*'
    rf'(?P<sym>D_(?P<addr>[0-9A-Fa-f]{{8}}))\s*\)*\s*(?:(?P<sign>[+-])\s*(?P<off>{NUMBER}))?\s*\)\s*\)')
_BARE = re.compile(r'(?<![\w&.>])(?P<sym>D_(?P<addr>[0-9A-Fa-f]{8}))\b(?!\s*\[)')


def _declared_words(source):
    """The address-named scalars declared with a 4-byte type."""
    return {hit['sym'] for hit in re.finditer(rf'\bextern\s+(?:volatile\s+)?{WORD}\s+(?P<sym>D_[0-9A-Fa-f]{{8}})\s*;', source)}


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    clear = _CLEAR.search(clean, part.opening + 1, part.end)
    if not clear:
        return []
    base, size = clear['sym'], int(clear['len'], 0)
    start = int(clear['addr'], 16)
    words = _declared_words(source)
    if base not in words or size % 4 or size <= 4:
        return []
    edits = []
    taken = []

    def element(address):
        delta = address - start
        return f'{base}[{delta // 4}]' if 0 <= delta < size and delta % 4 == 0 else None

    for hit in _CAST.finditer(clean, part.opening + 1, part.end):
        offset = int(hit['off'] or '0', 0) * (-1 if hit['sign'] == '-' else 1)
        target = element(int(hit['addr'], 16) + offset)
        if target and (hit['sym'] == base or hit['sym'] in words):
            edits.append((hit.start(), hit.end(), target))
            taken.append((hit.start(), hit.end()))
    for hit in _BARE.finditer(clean, part.opening + 1, part.end):
        if any(a <= hit.start() < b for a, b in taken):
            continue
        sym = hit['sym']
        target = element(int(hit['addr'], 16))
        if not target or sym not in words or clear.start('sym') <= hit.start() < clear.end('sym'):
            continue
        edits.append((hit.start(), hit.end(), target))
    if len(edits) < 2:
        return []
    edits.append((clear.start('amp') if clear['amp'] else clear.start('sym'), clear.end('sym'), base))
    declaration = re.search(rf'\bextern\s+((?:volatile\s+)?{WORD})\s+{re.escape(base)}\s*;', source)
    edits.append((declaration.start(), declaration.end(), f'extern {declaration[1]} {base}[];'))
    return [(FAMILY, edit(source, edits))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

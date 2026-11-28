"""An offset that is the low half of the symbol's own address, written as the symbol itself.

A disassembler pairs a `lui %hi(sym)` with the `%lo(sym)` of the access that uses it. When the access sits in another
block (a jump's delay slot, an arm reached only through a branch) the pairing can be lost, and the assembly shows the
raw immediate: `sw $a0, 0x5D54($v1)` beside `lui $v1, %hi(D_80075D54)`. m2c then reads the immediate as a field of the
symbol, `M2C_FIELD(&D_80075D54, s32 *, 0x5D54) = 1;`, a store to the wrong address that the compiler builds as
`0x5D54($v1)` off the symbol and no spelling around it repairs. The game stored to the symbol.

On a 26-instruction N64 state toggle (SN GCC 2.8.1, `-O2`) writing offset 0 took the machine draft from 800 to 760, and
`exit_run_outline` on that child matched it exactly.

`variants` reads `M2C_FIELD(&D_xxxxxxxx, T *, K)` and `*(T *)((s8 *)&D_xxxxxxxx + K)` (also `u8`/`char` casts) where
the symbol is named by its address and `K` is that address's low sixteen bits (as the assembler's signed immediate, or
written unsigned), and offers the same access at offset 0: one child for every such site, and one per site when there
are several. With the target's assembly, a site is offered only when the assembly has `%hi(sym)` and an access whose
offset is that raw number. A candidate only: the judge decides.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'symbol_low_half_offset'
FAMILIES = (FAMILY,)
LIMIT = 6

_NUMBER = r'(?P<k>-?\s*(?:0[xX][0-9A-Fa-f]+|\d+))'
_SYMBOL = r'(?P<symbol>D_(?P<address>[0-9A-Fa-f]{8}))'
_FIELD = re.compile(rf'(?<!\w)M2C_FIELD\(\s*&\s*{_SYMBOL}\s*,[^,;()]*\*\s*,\s*{_NUMBER}\s*\)')
_CAST = re.compile(rf'\(\s*(?:s8|u8|char)\s*\*\s*\)\s*&\s*{_SYMBOL}\s*\+\s*{_NUMBER}(?=\s*\))')
_RAW = re.compile(r'\b(?:l[bhw]u?|s[bhw]|[ls][wd]c1)\s+\$\w+\s*,\s*(-?(?:0[xX][0-9A-Fa-f]+|\d+))\(\$\w+\)')


def _is_low_half(offset, address):
    low = address & 0xFFFF
    return offset != 0 and offset in (low, low - 0x10000 if low & 0x8000 else low)


def _seen_raw(asm, symbol, offset):
    """The assembly lost the pairing: it builds `%hi(symbol)` and accesses memory at the bare immediate."""
    if f'%hi({symbol})' not in asm:
        return False
    return any(int(hit[1], 0) & 0xFFFF == offset & 0xFFFF for hit in _RAW.finditer(asm))


def variants(source, name, asm=''):
    part = view(source, name)
    if not part:
        return []
    uses = []
    for pattern in (_FIELD, _CAST):
        for hit in pattern.finditer(part.clean, part.opening, part.end):
            offset = int(re.sub(r'\s', '', hit['k']), 0)
            if not _is_low_half(offset, int(hit['address'], 16)):
                continue
            if asm and not _seen_raw(asm, hit['symbol'], offset):
                continue
            uses.append((hit.start('k'), hit.end('k'), '0'))
    if not uses:
        return []
    uses.sort()
    choices = [uses] + ([[use] for use in uses] if len(uses) > 1 else [])
    return [(FAMILY, edit(source, choice)) for choice in choices[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',),
          'order': 100}

"""A word or halfword of a local byte array that m2c read as one byte.

m2c declares a function's stack records as byte arrays (`u8 sp140[0x98];`) and writes an access at a computed offset as
`*(sp140 + offset)`, which is a one-byte access however wide the target's is (`lbu` against the game's `lw`). The child
casts the pointer to the width the target's own load or store has: `*(s32 *)(sp140 + offset)`, `s16`/`u16` for `lh`/
`lhu` (stores: `sh`). Only a width the target uses is offered, one child per access and width. Measured on an N64
function (SN GCC 2.8.1): 660 -> 460. Proposals only; the byte judge decides."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'stack_array_access_width'
FAMILIES = (FAMILY,)
LIMIT = 8
_ARRAY = re.compile(rf'(?m)^[ \t]*(?:u8|s8|char)\s+(?P<name>{IDENT})\s*\[[^\]]*\]\s*;')
_READS = (('lw', 's32'), ('lhu', 'u16'), ('lh', 's16'))
_WRITES = (('sw', 's32'), ('sh', 's16'))


def variants(source, name, asm):
    part = view(source, name)
    if not part or not asm:
        return []
    clean = part.clean
    used = set(re.findall(r'(?<![\w$.])(lw|lhu|lh|sw|sh)(?![\w.])', asm))
    out = []
    for array in _ARRAY.finditer(clean, part.opening, part.end):
        pattern = re.compile(rf'(?<![\w\])])(?<!\) )\*\s*\(\s*{array["name"]}\s*\+')
        for access in pattern.finditer(clean, array.end(), part.end):
            # `a * (sp + 1)` is a product, not a dereference
            if re.search(r'[\w\])]\s*$', clean[:access.start()]) and not re.search(r'\breturn\s*$', clean[:access.start()]):
                continue
            opening = clean.index('(', access.start())
            end = close(clean, opening, '(', ')')
            if not end:
                continue
            store = re.match(r'\s*=(?!=)', clean[end:])
            for mnemonic, kind in _WRITES if store else _READS:
                if mnemonic in used:
                    out.append((FAMILY, edit(source, [(access.start(), opening, f'*({kind} *)')])))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',),
          'order': 70}

"""A word global cast to a halfword or a byte, read as the halfword or byte the target loads at the symbol's address.

m2c reads `lhu $v0, %lo(D_800FDB9C)($v0)` of a symbol declared `u32` as `(u16) D_800FDB9C`, and `lh` as
`(s16) D_800FDB9C`. On a big-endian MIPS that cast is the word's low half, at offset 2: GCC loads the word (`lw`) and
keeps its low bits, or loads the halfword at `+2`, so the target's load at offset 0 (the high half) never comes out
and the program reads another field. Written as `*((u16 *) &D_800FDB9C)` the load is the target's. On a
1315-instruction KMC GCC 2.7.2 sound-sequence interpreter (`-G0 -mips3 -mgp32 -mfp32 -O2`) the seven reads of a command
word's first halfword were 115 to 300 points each, 16130 -> 14715 together.

`word_global_narrow_read`
    For each symbol the source declares as a 32-bit integer and the target loads at its own address (`%lo(SYM)`, no
    addend) with `lhu`/`lh`/`lbu`/`lb`, every cast `(T) SYM` to a type of that width (`u16`/`s16`/`unsigned short`/
    `short` for a halfword, `u8`/`s8`/`unsigned char`/`char` for a byte) is written `(*((T *) (&SYM)))`. Children:
    every such read at once, then each read alone (at most eight).

The width comes from the target's own loads; the exact judge decides each child.
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit

FAMILY = 'word_global_narrow_read'
FAMILIES = (FAMILY,)
LIMIT = 8
HALF = r'(?:u16|s16|unsigned\s+short|short|signed\s+short)'
BYTE = r'(?:u8|s8|unsigned\s+char|char|signed\s+char)'
WORD = r'(?:u32|s32|unsigned\s+int|unsigned\s+long|unsigned|int|long|signed\s+int)'


def _loads(asm):
    """`symbol -> {16, 8}`: the narrow widths the target loads at each symbol's own address."""
    found = {}
    for hit in re.finditer(r'\b(lhu|lh|lbu|lb)\s+\$\w+\s*,\s*%lo\(\s*(' + IDENT + r')\s*\)', asm or ''):
        found.setdefault(hit[2], set()).add(16 if hit[1].startswith('lh') else 8)
    return found


def variants(source, name, asm=''):
    span = find(source, name)
    loads = _loads(asm)
    if not span or not loads:
        return []
    clean = _blank(source)
    sites = []
    for symbol, widths in loads.items():
        if not re.search(r'\b(?:extern\s+)?(?:volatile\s+)?' + WORD + r'\s+' + re.escape(symbol) + r'\s*;', clean):
            continue
        kinds = [k for width, k in ((16, HALF), (8, BYTE)) if width in widths]
        for kind in kinds:
            pattern = (r'\(\s*(' + kind + r')\s*\)\s*(' + re.escape(symbol) + r')\b(?!\s*(?:\[|\.|->|\())')
            for hit in re.finditer(pattern, clean[span[0]:span[1]]):
                start = span[0] + hit.start()
                end = span[0] + hit.end()
                kind_text = re.sub(r'\s+', ' ', hit[1])
                sites.append((start, end, f'(*(({kind_text} *) (&{symbol})))'))
    if not sites:
        return []
    sites.sort()
    results = [(FAMILY, edit(source, sites))]
    if len(sites) > 1:
        for site in sites[:LIMIT]:
            results.append((FAMILY, edit(source, [site])))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',),
          'order': 90}  # the registry: no caller wiring (registry.py)

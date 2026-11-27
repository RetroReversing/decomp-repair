"""A constant word store into a table scaled by two, written as the halfword store the target has.

m2c types a store by the widest access it saw, so a halfword table written with a small constant can come out as
`*(s32 *)((idx * 2) + D_800BE210) = 0x19;` (`sw`) where the target has `sh`. `narrow_store_width` takes the width from
a cast on the stored value or from the offset of a field; a table store has neither, but its index is scaled by the
element size (`* 2`, `<< 1`), and the target's stores say the width. A `*(s32|u32|int *)(...) = K;` whose address has a
scale of two, K fitting a halfword and the target storing halfwords (`sh`) while no word store beyond the stack
(`sw` off a base other than `$sp`) is among its stores (or the scale alone, when the target has `sh`) becomes
`*(s16 *)(...)` (`u16` above 0x7FFF, the constant materialised as it is). One child with every such store, then one each
(the first 6). Measured on a one-function matching case (an SN GCC 2.7.2 -O1 N64 game): `sw` against the target's `sh`,
exact once the store was `s16`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'indexed_store_width'
FAMILIES = (FAMILY,)
LIMIT = 6

WORD = r'(?:s32|u32|int|unsigned\s+int|long)'
STORE = re.compile(r'\b(sw|sh)\s+\$\w+\s*,\s*(?:-?(?:0x[0-9a-fA-F]+|\d+)|%lo\([^)]*\))?\(\s*\$(\w+)\s*\)')
SCALE = re.compile(r'\*\s*2\b|\b2\s*\*|<<\s*1\b')
NUMBER = r'(?:0x[0-9a-fA-F]+|\d+)'


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    stores = STORE.findall(asm)
    if not any(op == 'sh' for op, _ in stores):
        return []
    words = any(op == 'sw' and base not in ('sp', 'fp') for op, base in stores)
    clean = _blank(source)
    sites = []
    for m in re.finditer(r'\*\s*\(\s*\(?\s*(?P<type>' + WORD + r')\s*\*\s*\)', clean[span[0]:span[1]]):
        at = span[0] + m.end()
        while clean[at:at + 1].isspace():
            at += 1
        end = close(clean, at) if clean[at:at + 1] == '(' else None
        if not end:
            continue
        tail = re.match(r'\s*\)?\s*=\s*(' + NUMBER + r')\s*;', clean[end:])
        if not tail or int(tail[1], 0) > 0xFFFF:
            continue
        if not SCALE.search(clean[at:end]) and words:
            continue
        start = span[0] + m.start('type')
        kind = 'u16' if int(tail[1], 0) > 0x7FFF else 's16'
        sites.append((start, span[0] + m.end('type'), kind))
    if not sites:
        return []

    def apply(chosen):
        text = source
        for a, b, new in sorted(chosen, reverse=True):
            text = text[:a] + new + text[b:]
        return text
    result = [apply(sites)]
    if len(sites) > 1:
        result += [apply([site]) for site in sites[:LIMIT]]
    return [(FAMILY, text) for text in dict.fromkeys(result) if text != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}

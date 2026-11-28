"""The low byte (or half) of a word table's element, read as the word narrowed and not through its address.

m2c writes the load `lbu $v0, 3($v0)` of a word as `M2C_FIELD(addr, u8 *, 3)`. When `addr` is an element of a global
table, GCC folds the `+ 3` into the symbol's own relocation (`lui %hi(table + 3)`) and loads `0($v0)`. The target
keeps the address of the element and the offset in the load: the source read the word and narrowed it, `(u8) table[i]`.

word_low_byte_read
    `M2C_FIELD(&words[i], u8 *, 3)` becomes `(u8) words[i]`, and `u16 *, 2` becomes `(u16) words[i]`, for an array
    this source declares with a word type, when the target has that load. Big-endian MIPS only: elsewhere those offsets
    are the word's high end.

Seen on an SN GCC 2.8.1 (`-G0 -mips3 -O2 -meb`) N64 label update, 450 with the field read and 0 narrowed (one
function, a controlled result).
"""
import re

from .csource import _blank, find
from .integer_repair_support import edit
from .pattern_repairs import close

FAMILY = 'word_low_byte_read'
FAMILIES = (FAMILY,)

_WORDS = re.compile(r'(?m)^[ \t]*extern\s+(?:s32|u32|int)\s+([A-Za-z_]\w*)\s*(?:\[\w*\]\s*)+;')
_PARTS = (('u8', 3, 'lbu'), ('s8', 3, 'lb'), ('u16', 2, 'lhu'), ('s16', 2, 'lh'))


def variants(source, name, asm, arch='mips'):
    span = find(source, name)
    if not span or not asm or arch != 'mips' or 'M2C_FIELD' not in source:
        return []
    clean = _blank(source)
    words = set(_WORDS.findall(clean))
    edits = []
    for hit in re.finditer(r'\bM2C_FIELD\s*\(', clean[span[0]:span[1]]):
        opening = span[0] + hit.end() - 1
        end = close(clean, opening)
        if not end:
            continue
        for kind, offset, load in _PARTS:
            tail = re.search(rf',\s*{kind}\s*\*\s*,\s*(?:{offset}|0x{offset})\s*$', clean[opening + 1:end - 1])
            if not tail or not re.search(rf'\b{load}\s+\$\w+\s*,\s*(?:0x{offset}|{offset})\(', asm):
                continue
            address = source[opening + 1:opening + 1 + tail.start()].strip()
            while address.startswith('(') and close(address, 0) == len(address):
                address = address[1:-1].strip()
            element = re.fullmatch(r'&\s*(([A-Za-z_]\w*)\s*\[.+\])', address, re.S)
            if element and element[2] in words:
                edits.append((span[0] + hit.start(), end, f'(({kind}) {element[1]})'))
    return [(FAMILY, edit(source, edits))] if edits else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'arch')}

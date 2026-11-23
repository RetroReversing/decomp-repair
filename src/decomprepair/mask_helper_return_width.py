"""An inline mask helper whose return type is narrower than its mask.

m2c writes the `& 0xFFFF` of a halfword it reloaded as a tiny inline helper, `inline_fn(u16 arg0) { return arg0 &
0xFFFF; }`, and gives it the narrowest return type its reading of the call sites allowed (`unsigned char`). Called
through `* 0x18` or compared with a halfword, that return type makes the compiler mask the value to a byte
(`andi $v0,$v0,0xff`) where the target masks a halfword (`andi $v0,$v0,0xffff`). Widening the helper's return type to
`unsigned short` (the mask's own width) changed both rows on a KMC `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`
menu-update function (590 -> 415, the rest being allocation). Only a function in the source whose whole body is
`return param & MASK;` with a mask of 0xFFFF and a return type of one byte is changed. A candidate for the exact
judge, never a verdict."""
import re

from .csource import _blank
from .integer_repair_support import edit

FAMILY = 'mask_helper_return_width'
FAMILIES = (FAMILY,)
HELPER = re.compile(
    r'(?P<head>(?:inline\s+static|static\s+inline|inline)\s+)(?P<type>unsigned\s+char|signed\s+char|char|u8|s8)(?P<gap>\s+)'
    r'(?P<name>[A-Za-z_]\w*)\s*\(\s*(?:u16|s16|unsigned\s+short|short|s32|u32|int|unsigned(?:\s+int)?)\s+(?P<arg>[A-Za-z_]\w*)\s*\)\s*'
    r'\{\s*return\s+(?P=arg)\s*&\s*(?:0[xX][fF]{4}|65535)[uU]?\s*;\s*\}')


def variants(source, name, header=''):
    out = []
    for m in HELPER.finditer(_blank(source)):
        out.append(edit(source, [(m.start('type'), m.end('type'), 'unsigned short')]))
    return [(FAMILY, c) for c in dict.fromkeys(out) if c != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 140}

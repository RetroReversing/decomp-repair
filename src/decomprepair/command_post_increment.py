"""m2c's `cmd = list; list += 8;` through a byte pointer, written as the post-increment of a two-word record.

A display list (or any command queue) is written `cmd = list++;` in the game's source, usually through a macro with
its own local. m2c prints the global as a byte or `void` pointer and the advance as a statement of its own:

    cmd = gList;                      ->    cmd = (*(M2CCommandPair **) &gList)++;
    gList += 8;

KMC and SN GCC keep a second register for the old value of the post-increment (`move $a0,$v0; addiu $v0,$v0,8`),
which the two statements lose: the global is loaded straight into the local's register. Measured on a
75-instruction N64 display-list and matrix load (SN GCC 2.8.1, `-O2 -G0 -mips3`), with `arm_symbol_copy_tail`'s
child as the parent: 1080 before, byte-identical after. One function.

The cast keeps the global's declaration, so its other uses read as before; the program is the same."""
import re

from .csource import _blank, find

FAMILY = 'command_post_increment'
FAMILIES = (FAMILY,)
ID = r'[A-Za-z_]\w*'
RECORD = 'M2CCommandPair'
TYPEDEF = f'typedef struct {{ unsigned int w0; unsigned int w1; }} {RECORD};\n'
ADVANCE = re.compile(rf'(?<![\w.>])(?P<t>{ID})\s*=\s*(?P<p>{ID})\s*;\s*'
                     rf'(?:(?P=p)\s*\+=\s*(?:8|0x8)|(?P=p)\s*=\s*(?P=t)\s*\+\s*(?:8|0x8))\s*;')
BYTE_POINTER = r'(?:^|;|\}})\s*(?:extern\s+)?(?:void|u8|s8|char|unsigned\s+char|signed\s+char)\s*\*\s*{}\s*;'


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    context = clean[:span[0]] + '\n' + _blank(header)
    hits = [m for m in ADVANCE.finditer(clean, opening, span[1])
            if re.search(BYTE_POINTER.format(m['p']), context, re.M)]
    if not hits:
        return []
    child = source
    for m in reversed(hits):
        child = child[:m.start()] + f"{m['t']} = (*({RECORD} **) &{m['p']})++;" + child[m.end():]
    if not re.search(rf'\b{RECORD}\s*;', context):
        child = child[:span[0]] + TYPEDEF + child[span[0]:]
    return [(FAMILY, child)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 61}

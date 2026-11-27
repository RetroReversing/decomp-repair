"""A narrow global read that the target masks again: the game declared it `volatile`.

gcc reads a `u16` with `lhu`, which already clears the upper half, so `if (G != 5)` and `if ((u16) G != 5)` compile to
no mask. A target that has `lhu $v0, %lo(G)($v0); andi $v0, $v0, 0xffff` (or `lbu` and `andi 0xff`) loaded it as an
access gcc would not fold into the extension, which a `volatile` global is (seen with KMC gcc 2.7.2 at `-O1`; the
reason inside the compiler is a hypothesis). A 296-instruction state routine was 180 from this one word and exact with
`extern volatile u16 G;`. Offered for each such global the function declares, one at a time and together. `volatile`
only adds accesses, so the meaning stays.
"""
import re

from .csource import _blank, find

FAMILY = 'remask_volatile'
FAMILIES = (FAMILY,)

_LOAD = re.compile(r'\b(lhu|lbu)\s+\$(\w+)\s*,\s*%lo\(\s*([A-Za-z_]\w*)\s*\)\(\$\w+\)')
_MASK = {'lhu': 0xFFFF, 'lbu': 0xFF}


def _masked(asm):
    """The globals whose narrow load the next instruction masks to its own width."""
    lines = [line for line in asm.splitlines() if line.strip() and not line.strip().startswith(('.', 'glabel'))]
    found = []
    for line, after in zip(lines, lines[1:]):
        load = _LOAD.search(line)
        if not load:
            continue
        mask = re.search(r'\bandi\s+\$\w+\s*,\s*\$' + load[2] + r'\s*,\s*(0[xX][0-9A-Fa-f]+|\d+)', after)
        if mask and int(mask[1], 0) == _MASK[load[1]] and load[3] not in found:
            found.append(load[3])
    return found


def variants(source, name, asm=''):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    places = []
    for symbol in _masked(asm)[:4]:
        decl = re.search(r'(?m)^[ \t]*extern\s+(?=(?:(?:unsigned|signed)\s+)?(?:u8|u16|s8|s16|char|short)\s+' + symbol
                         + r'\s*;)', clean[:span[0]])
        if decl:
            places.append(decl.end())

    def apply(offsets):
        text = source
        for at in sorted(offsets, reverse=True):
            text = text[:at] + 'volatile ' + text[at:]
        return text

    result = [(FAMILY, apply([at])) for at in places]
    if len(places) > 1:
        result.append((FAMILY, apply(places)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}

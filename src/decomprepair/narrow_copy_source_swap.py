"""A narrow local assigned an expression and then copied into a wide one (`s16 t = a + b; v = t;`) written the other
way round: the wide local takes the expression and the narrow one is its copy (`v = a + b; t = v;`).

KMC GCC 2.7.2 (`-O2`, N64) keeps an `s16`/`u16`/`s8`/`u8` local in a narrow pseudo (MIPS defines no PROMOTE_MODE), so
`t = a + b; v = t;` makes the wide `v` the sign- or zero-extension of the narrow value: the extension (`sll; sra`) is
what both the copy and the tests read, and the copy lands in the extension's register. A target that copies the raw
sum (`addu $v0, ..; move $a1, $v0; sll $v0, $v0, 16; sra $v0, $v0, 16; bltz $v0`) had the sum in the wide local and the
tests on the narrow copy. On a 1315-instruction sound-sequence interpreter's group-link command (a byte field plus a
halfword clamped to 0..255), 3565 -> 3560. The reading is from the output; the judge decides.

Rewrites two adjacent statements `N = E; W = N;` where `N` is a narrow local, `W` a wide one (`s32`, `u32`, `int`,
`long`), both declared in the function, and `E` names neither. Bounded to `LIMIT` children.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'narrow_copy_source_swap'
FAMILIES = (FAMILY,)
LIMIT = 6
_NARROW = r'(?:u8|s8|u16|s16|unsigned char|signed char|unsigned short|short|char)'
_WIDE = r'(?:u32|s32|int|long|unsigned int|unsigned long|unsigned)'


def _declared(body, kind, name):
    return re.search(rf'(?m)^[ \t]*(?:register\s+)?{kind}[ \t]+{re.escape(name)}[ \t]*;', body) is not None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    body = clean[lo:hi]
    out = []
    pair = re.compile(rf'(?m)^(?P<i1>[ \t]*)(?P<n>{IDENT})\s*=(?!=)\s*(?P<e>[^;{{}}]+);[ \t]*\n'
                      rf'(?P<i2>[ \t]*)(?P<w>{IDENT})\s*=\s*(?P=n)\s*;[ \t]*\n')
    for found in pair.finditer(clean, lo, hi):
        narrow, wide = found['n'], found['w']
        expr = source[found.start('e'):found.end('e')]
        if narrow == wide or re.search(rf'\b(?:{re.escape(narrow)}|{re.escape(wide)})\b', expr):
            continue
        if not (_declared(body, _NARROW, narrow) and _declared(body, _WIDE, wide)):
            continue
        text = (source[:found.start()] + f'{found["i1"]}{wide} = {expr.strip()};\n{found["i2"]}{narrow} = {wide};\n'
                + source[found.end():])
        out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)

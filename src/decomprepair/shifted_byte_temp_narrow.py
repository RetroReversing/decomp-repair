"""The high byte of a 16-bit pair, held in a word local that is shifted left by 8 in place, declared as the halfword it becomes (GCC 2.7.2, KMC, N64).

`u32 yHigh; ... yHigh = q[2]; yHigh <<= 8; y = yHigh + yLow;` keeps a word-sized local for a value that is a byte before
the shift and at most 0xFF00 after it. A search leaves it `u32`; the game's temporary was a halfword (`u16`), which changes
the quantity's machine mode and so which pseudo the allocator ranks first and which register the loads take. Measured on a
559-instruction N64 display-list builder (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): 35 -> 20 for one of three such
temporaries in a loop (the other two, and the adds that use them, did not move; each alone is a separate step, and the three
are composable).

`variants` takes each word-sized local that is assigned from an array read and shifted left in place by at most 8
(`name <<= 8;`, `name = name << 8;`, or the same inside a comma list) and is not otherwise written, and declares it
`u16` (`shifted_byte_temp_narrow`): one child per local, and one child for all of them. A local that is read as a word
anywhere else (compared, stored through a pointer, passed on) is left alone.
"""
import re

from .csource import find

FAMILY = 'shifted_byte_temp_narrow'
FAMILIES = (FAMILY,)
MAX_CHILDREN = 8

_ID = r'[A-Za-z_]\w*'
_DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>u32|s32|int|unsigned int|unsigned)[ \t]+(?P<name>{_ID})[ \t]*;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    text = source[span[0]:span[1]]
    found = []
    for decl in _DECL.finditer(text):
        var = decl['name']
        v = re.escape(var)
        shift = re.search(rf'(?<![\w.>]){v}\s*<<=\s*[1-8]\b|(?<![\w.>]){v}\s*=\s*{v}\s*<<\s*[1-8]\b', text)
        reads = list(re.finditer(rf'(?<![\w.>]){v}\s*=(?!=)\s*[\w.>\-]+\s*\[[^\]]*\]\s*[,;)]', text))
        writes = list(re.finditer(rf'(?<![\w.>]){v}\s*(?:=(?!=)|[-+*/|&^%]=|<<=|>>=|\+\+|--)|(?:\+\+|--)\s*{v}\b|&\s*{v}\b', text))
        if not shift or len(reads) != 1 or len(writes) != 2:
            continue
        # the shifted value is only used as an operand of an add or or, never compared, stored or passed on by itself
        uses = [m for m in re.finditer(rf'(?<![\w.>]){v}\b', text) if not decl.start() <= m.start() < decl.end()]
        if len(uses) != 3:  # the read, the shift and the one use of the shifted value
            continue
        found.append(decl)
    out = []
    for decl in found[:MAX_CHILDREN - 1]:
        out.append((FAMILY, _narrow(source, span, text, [decl])))
    if len(found) > 1:
        out.append((FAMILY, _narrow(source, span, text, found)))
    return out


def _narrow(source, span, text, decls):
    for decl in sorted(decls, key=lambda d: d.start(), reverse=True):
        text = text[:decl.start('type')] + 'u16' + text[decl.end('type'):]
    return source[:span[0]] + text + source[span[1]:]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

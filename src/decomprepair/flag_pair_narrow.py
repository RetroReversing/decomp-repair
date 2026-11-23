"""A flag and the temporary that masks it, both typed `char`: `t = flag & mask; flag = t;`.

m2c types a flag `long` and the value `flag & mask` produces `int`, and the compiler then folds the copy `flag = t` into
the `and` (`and $s3,$s3,$v0`). The game's flag is a byte: with the flag and the temporary typed `char` the copy into a
byte pseudo stays a `move` (`and $v0,$s3,$v0; move $s3,$v0`), the test of the temporary keeps the register the `and`
wrote, and the extension a byte read would need is dropped because only the low byte of the result is used (the same
bytes as the target's `sll $v0,$v0,0x18; beqz`). In a 970-instruction N64 state-machine handler (`gcc-2.7.2-kmc -G0
-mips3 -mgp32 -mfp32 -O2`) typing the merged flag and its temporary `char` was the last step: 230 -> 0. Typing only
one of the two was 320 and 300, the flag alone (the other left `int`) 320: the pair is one child.

`variants` finds a statement `T = F & expr;` directly followed by `F = T;` (one statement per line) where `F` and `T`
are word-sized integer locals (`long`, `int`, `s32`, `u32`) or `char`-sized ones already, and offers both declarations
retyped `char` (one child) and `s8` (another). Locals whose address is taken are left alone. At most 2 children. A
candidate rewrite: the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, _address_taken, view
from .line_scan import apply, lines

FAMILY = 'flag_pair_narrow'
FAMILIES = (FAMILY,)
TYPES = ('char', 's8')
WORD = r'(?:long|int|s32|u32|unsigned\s+int|unsigned|signed\s+int)'
PAIR = re.compile(rf'(?P<t>{IDENT})\s*=\s*(?P<f>{IDENT})\s*&\s*[^;]+;')


def _declaration(part, name):
    return re.search(rf'(?m)^[ \t]*(?P<type>{WORD}|char|s8|u8)\s+{re.escape(name)}\s*;', part.clean[part.opening:part.end])


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    found = None
    for index in range(len(body) - 1):
        pair = PAIR.fullmatch(body[index].stripped)
        if not pair or pair['t'] == pair['f']:
            continue
        if not re.fullmatch(rf'{re.escape(pair["f"])}\s*=\s*{re.escape(pair["t"])}\s*;', body[index + 1].stripped):
            continue
        flag, temp = _declaration(part, pair['f']), _declaration(part, pair['t'])
        if not flag or not temp or _address_taken(part.body, pair['f']) or _address_taken(part.body, pair['t']):
            continue
        if {flag['type'], temp['type']} <= {'char', 's8', 'u8'}:
            continue
        found = (flag, temp)
        break
    if not found:
        return []
    out = []
    for kind in TYPES:
        edits = []
        for decl in found:
            edits.append((part.opening + decl.start('type'), part.opening + decl.end('type'), kind))
        out.append(apply(source, sorted(edits)))
    return [(FAMILY, child) for child in dict.fromkeys(out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

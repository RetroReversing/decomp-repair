"""A sum stored into a halfword, whose 16-bit constant is written unsigned so the compiler keeps the word-sized add.

m2c writes a halfword's address arithmetic with the constant as the 16-bit pattern of a negative number
(`D + (x + 0xFFC7)` stored through `*(u16 *)`, where the game had `D + x - 0x39` or the like). With a signed halfword
operand GCC's fold narrows the whole sum to the destination's width and turns the constant into `-0x39`: `addiu $v0, $t0, -0x39`.
The target kept the 32-bit constant (`ori $v0, $zero, 0xFFC7; addu $v0, $t0, $v0`, twice, one per store); writing the
constant `0xFFC7U` kept it (1840 -> 1625 on a 534-instruction panel builder, for the two stores). The explanation (fold-const
converting `(unsigned short) (a + b)` to a narrower add only when no operand is unsigned int) is a hypothesis.

`variants` finds a store whose left side is a halfword (`*(u16 *)...`, `*(s16 *)...`, `*((u16 *) ...)`, or an element or
scalar of an `extern u16`/`s16` the file declares) and whose right side
has `+ 0xHHHH` with the constant between 0x8000 and 0xFFFF and no suffix, and writes every such constant with `U`. One child."""
import re

from .csource import _blank, find

FAMILY = 'narrow_sum_unsigned_constant'
FAMILIES = (FAMILY,)
STORE = re.compile(r'(?:(?<=[;{}])|(?m:^))(?:[ \t\n]*do\s*\{)?[ \t]*(?:\(\s*)?\*\s*\(?\s*\(?\s*(?:u16|s16|unsigned\s+short|short)\s*\*\s*\)[^=;]*?=(?!=)\s*(?P<right>[^;]*);')
CONSTANT = re.compile(r'(?<![\w.])(?P<c>0[xX][0-9a-fA-F]{4})(?![\w])')


def _stores(clean, span):
    yield from STORE.finditer(clean, span[0], span[1])
    names = {m['n'] for m in re.finditer(r'(?m)^[ \t]*extern\s+(?:u16|s16|unsigned\s+short|short)\s+(?P<n>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])*\s*;', clean[:span[0]])}
    if names:
        pattern = re.compile(r'(?:(?<=[;{}])|(?m:^))(?:[ \t\n]*do\s*\{)?[ \t\n]*(?:' + '|'.join(map(re.escape, sorted(names))) + r')\s*(?:\[[^\];]*\])*\s*=(?!=)\s*(?P<right>[^;]*);')
        yield from pattern.finditer(clean, span[0], span[1])


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    edits = []
    for hit in _stores(clean, span):
        for number in CONSTANT.finditer(clean, hit.start('right'), hit.end('right')):
            value = int(number['c'], 16)
            if 0x8000 <= value <= 0xFFFF and clean[number.end('c'):number.end('c') + 1] not in 'uUlL':
                edits.append(number.end('c'))
    if not edits:
        return []
    out = source
    for at in sorted(set(edits), reverse=True):
        out = out[:at] + 'U' + out[at:]
    return [(FAMILY, out)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 67}

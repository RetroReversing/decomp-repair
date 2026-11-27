"""A byte's sign bit tested as `& 0x80`, written as a signed byte compared with zero.

A byte counter that counts down and wraps (`n = *(u8 *) p - 1; *(u8 *) p = n; if (n & 0x80) { reload }`) is a signed
byte in the game: `if (n < 0)`. Spelled as a mask the compiler tests `andi $v0, $v0, 0x80` / `beqz`; a signed byte
compared with zero is `sll $v0, $v0, 0x18` / `bgez`, the target's two instructions, and it leaves the branch's
delay slot to the instruction that was waiting for it (KMC GCC 2.7.2: 1900 -> 1600 in one 557-instruction function,
with the counter's own local instead of a cast through a pointer-typed one).

`halfword_sign_test` is the halfword's: m2c writes a signed halfword countdown as `t = *(u16 *) p - 1; *(u16 *) p = t;
if (t & 0x8000)`, which compiles `andi $v0, $v0, 0x8000` / `beqz` where the target has `sll $v0, $v0, 0x10` / `bgez`.
The test written `(s16) t < 0` is those two instructions (a 146-instruction KMC GCC 2.7.2 `-O1` routine: 400 -> 0).

A proposal takes a plain `u8`/`unsigned char` local `n` whose only tests are `n & 0x80` as a whole `if` condition
(or its negation) and declares it `s8` with the tests `n < 0` (`n >= 0`); a local that is already signed gets the
tests alone. Nothing else about the local changes: stores of it as a byte and the arithmetic that feeds it keep their
meaning, because the byte is truncated the same way. MIPS only.
"""
import re

from .csource import find
from .integer_repair_support import edit, view

FAMILY = 'byte_sign_test'
HALFWORD = 'halfword_sign_test'
FAMILIES = (FAMILY, HALFWORD)

_UNSIGNED = r'(?:u8|unsigned\s+char)'
_SIGNED = r'(?:s8|signed\s+char)'


def variants(source, name, arch='mips'):
    """Proposals: signed byte locals tested against zero instead of masked with 0x80."""
    if arch != 'mips' or not find(source, name):
        return []
    part = view(source, name)
    if not part:
        return []
    out = []
    declarations = list(re.finditer(rf'(?m)^[ \t]*({_UNSIGNED}|{_SIGNED})[ \t]+([A-Za-z_]\w*)[ \t]*;', part.clean[part.opening:part.end]))
    for declaration in declarations:
        local = declaration[2]
        body = part.clean[part.opening+1:part.end-1]
        tests = list(re.finditer(rf'\bif\s*\(\s*(!?)\s*\(?\s*{re.escape(local)}\s*&\s*(?:0x80|128)\s*\)?\s*\)', body))
        masks = len(re.findall(rf'\b{re.escape(local)}\s*&\s*(?:0x80|128)\b', body))
        if not tests or masks != len(tests):
            continue
        edits = []
        for test in tests:
            at = part.opening + 1 + test.start()
            opening = source.index('(', at)
            closing = part.opening + 1 + test.end()
            edits.append((opening, closing, f'({local} {">=" if test[1] else "<"} 0)'))
        if re.match(_UNSIGNED, declaration[1]):
            start = part.opening + declaration.start(1)
            edits.append((start, start + len(declaration[1]), 's8'))
        child = edit(source, edits)
        if child != source:
            out.append((FAMILY, child))
    return list(dict.fromkeys(out))[:6] + _halfwords(source, part)


def _halfwords(source, part):
    """Each 16-bit local's `& 0x8000` conditions written as the signed halfword compared with zero."""
    body = part.clean[part.opening + 1:part.end - 1]
    out = []
    for local in dict.fromkeys(re.findall(r'(?m)^[ \t]*(?:u16|s16|unsigned\s+short|short)[ \t]+([A-Za-z_]\w*)[ \t]*;', body)):
        tests = re.finditer(rf'\bif\s*\(\s*(!?)\s*\(?\s*{local}\s*&\s*(?:0x8000|32768)[uU]?\s*\)?\s*\)', body)
        edits = []
        for test in tests:
            at = part.opening + 1 + test.start()
            edits.append((source.index('(', at), part.opening + 1 + test.end(),
                          f'((s16) {local} {">=" if test[1] else "<"} 0)'))
        if edits:
            out.append((HALFWORD, edit(source, edits)))
    return out[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'arch'), 'order': 70}  # the registry: no caller wiring (registry.py)

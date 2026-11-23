"""A counted loop's unsigned counter, retyped as the signed word the game counted with.

A `while (n-- != 0)` (or `if (n-- != 0) do { } while (n-- != 0);`) test is the old value of `n` against zero. With an
unsigned `n` GCC 2.7.2's combine rewrites it as `n - 1 != 0xFFFFFFFF` and spends a register on the -1; with a signed
`n` the old value is kept in a copy and tested against zero, which is what a game that counted with an `int` has
(`move $v0, $n; ...; bnez $v0` with the decrement in the delay slot). m2c types every counter it cannot see the sign
of as `u32`, so the saved drafts carry the unsigned word.

This changes the declaration of one local, `u32 n;` / `unsigned n;` / `unsigned int n;` to `s32 n;` / `int n;`, for a
local that is tested by a postdecrement against zero somewhere in the function and has no other signedness reading
(it is never compared with `<`, `<=`, `>`, `>=`, divided, shifted right, or widened to a 64-bit type), so the signed
word does what the unsigned one did. Hypothesis, not a compiler fact: the target's `move`-then-test shape is what the
signed declaration produces in the cases it was measured on (a 681-instruction bit-stream decoder: 12971 -> 11781).
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'signed_postdec_counter'
FAMILIES = (FAMILY,)

SIGNED = {'u32': 's32', 'unsigned': 'int', 'unsigned int': 'int'}


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    context = _blank(header) + '\n' + part.clean
    if re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    out = []
    pattern = re.compile(rf'(?:(?<=[;{{}})])|^)\s*(?P<type>unsigned\s+int|unsigned|u32)\s+(?P<name>{IDENT})\s*;')
    for hit in pattern.finditer(part.clean, part.opening + 1, part.end):
        counter = hit['name']
        body = part.body
        if not re.search(rf'\b{counter}\s*--\s*(?:!=|==)\s*0\b|\(\s*{counter}\s*--\s*\)', body):
            continue
        if len(re.findall(rf'\b(?:unsigned\s+int|unsigned|u32|s32|int|u16|s16|u8|s8)\s+{counter}\b', body)) != 1:
            continue  # shadowed or redeclared: a second binding of the name
        left = rf'\b{counter}\s*(?:<=|>=|<(?![<=])|>(?![>=])|/|%|>>(?!=))'
        right = rf'(?:(?<![<>])(?:<=|>=)|(?<![<>])<(?![<=])|(?<![<>])>(?![>=])|/|%)\s*{counter}\b'
        if re.search(left + '|' + right, body):
            continue  # an ordering, a division or a logical shift of it: the sign is read there
        if re.search(rf'&\s*{counter}\b(?!\s*[&|])', body) and re.search(rf'(?<![&\w])&\s*{counter}\b', body):
            continue  # its address is taken
        kind = re.sub(r'\s+', ' ', hit['type'])
        if kind == 'u32':
            typedefs = re.findall(r'\btypedef\s+([^;{}]+)\s+u32\s*;', context)
            if typedefs and typedefs != ['unsigned int']:
                continue
        start = hit.start('type')
        out.append((FAMILY, edit(source, [(start, hit.end('type'), SIGNED[kind])])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}

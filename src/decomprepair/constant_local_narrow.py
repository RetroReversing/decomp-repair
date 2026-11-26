"""A local that only ever holds small constants, declared as narrow as they are.

m2c and hand drafts declare such a local `s32`. gcc 2.7.2 then keeps a copy of it in other registers than the game's
code did, where the local was a halfword: on a 76-instruction KMC `-O1` easing routine (a switch assigns 0, 2, 0x50 or
0xA0) retyping it to `s16` alone went 605 to 80, and it matched after the two `computed_compare_flip` and
`compound_value_first` steps. No existing family narrows a local without a cast that already names the width.

The rewrite only fires when it cannot change behaviour: every write is a plain assignment of an integer literal that
fits the narrow type, and the local's address is never taken.
"""
import re

from .arm_block_support import IDENT
from .integer_repair_support import edit, view

FAMILY = 'constant_local_narrow'
FAMILIES = (FAMILY,)

DECL = re.compile(rf'(?<=[;{{}}])\s*(?P<type>s32|int|u32)\s+(?P<name>{IDENT})\s*(?P<init>=\s*[^;,]+)?;')
LITERAL = re.compile(r'\s*(-?\s*(?:0[xX][0-9a-fA-F]+|\d+))\s*')
RANGES = (('s16', -0x8000, 0x7FFF), ('u16', 0, 0xFFFF), ('s8', -0x80, 0x7F), ('u8', 0, 0xFF))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    out = []
    for hit in DECL.finditer(body):
        var = hit['name']
        if re.search(rf'&\s*{var}\b|(?:\+\+|--)\s*{var}\b|\b{var}\s*(?:\+\+|--|(?:<<|>>|[-+*/%&|^])=)', body):
            continue
        if len(re.findall(rf'\b(?:s32|int|u32|s16|u16|s8|u8|short|char|f32|float)\b[\s*]+{var}\b', body)) != 1:
            continue
        values = [match[1] for match in re.finditer(rf'(?<![.>\w]){var}\s*=(?!=)([^;]*);', body)]
        numbers = [LITERAL.fullmatch(value) for value in values]
        if not values or not all(numbers):
            continue
        values = [int(match[1].replace(' ', ''), 0) for match in numbers]
        for type_, low, high in RANGES:
            if all(low <= value <= high for value in values):
                at = part.opening + hit.start('type')
                text = edit(source, [(at, part.opening + hit.end('type'), type_)])
                if (FAMILY, text) not in out:
                    out.append((FAMILY, text))
        if len(out) >= 8:
            break
    return out[:8]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 92}  # the registry: no caller wiring (registry.py)

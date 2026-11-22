"""Two stores to different elements of one local array, written in the other order.

GCC 2.7.2's first scheduler keeps the order of independent stores whose values have no other constraint, so the
order the C writes them is the order of the instructions. m2c writes the stores of a small stack argument array in
the order of the target's offsets (`a[1] = 0; a[2] = x;`) where the game computed the loaded value first and wrote
the constant second: a KMC N64 function (`-G0 -mips3 -mgp32 -mfp32 -O2`, 731 instructions) went 979 -> 919 with
`a[2] = x; a[1] = 0;`, the `sh $zero` landing after the argument setup of the call as the target has it.

Offered for two consecutive statements `ARR[i] = E;` and `ARR[j] = F;` with literal different indices, one local
array, and no call in either value or mention of the array in it. The rewrite swaps them. A candidate: the judge's
byte comparison decides whether the order matters.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'adjacent_array_store_order'
FAMILIES = (FAMILY,)
LIMIT = 40
STORE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<array>{IDENT})\[\s*(?P<index>{NUMBER})\s*\]\s*=(?!=)\s*(?P<value>[^;{{}}]*);[ \t]*\n')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    arrays = set(re.findall(rf'\b(?:[su](?:8|16|32)|f32|char|short|int|float)\s+({IDENT})\s*\[[^\]]*\]\s*;',
                            part.clean[:part.end]))
    result = []
    for first in STORE.finditer(part.clean, part.opening, part.end):
        second = STORE.match(part.clean, first.end())
        if (not second or first['array'] not in arrays or second['array'] != first['array']
                or second['indent'] != first['indent'] or int(first['index'], 0) == int(second['index'], 0)):
            continue
        values = first['value'] + ' ' + second['value']
        if re.search(rf'\b{IDENT}\s*\(', values.replace('M2C_FIELD(', '').replace('sizeof(', '')) \
                or re.search(rf'\b{re.escape(first["array"])}\b', values):
            continue
        text = source[second.start():second.end()] + source[first.start():first.end()]
        result.append((FAMILY, edit(source, [(first.start(), second.end(), text)])))
        if len(result) >= LIMIT:
            break
    return result

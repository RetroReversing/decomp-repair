"""Two stores to different elements of one local array, written in the other order.

GCC 2.7.2's first scheduler keeps the order of independent stores whose values have no other constraint, so the
order the C writes them is the order of the instructions. m2c writes the stores of a small stack argument array in
the order of the target's offsets (`a[1] = 0; a[2] = x;`) where the game computed the loaded value first and wrote
the constant second: a KMC N64 function (`-G0 -mips3 -mgp32 -mfp32 -O2`, 731 instructions) went 979 -> 919 with
`a[2] = x; a[1] = 0;`, the `sh $zero` landing after the argument setup of the call as the target has it.

Offered for two consecutive statements `ARR[i] = E;` and `ARR[j] = F;` with literal different indices, one local
array, and no call in either value or mention of the array in it. The rewrite swaps them. A candidate: the judge's
byte comparison decides whether the order matters.

Also offered for two consecutive stores to different fields of one array's elements, on one line or two
(`D[i].prev = &D[i - 1]; D[i - 1].next = &D[i];`), whose values only compute addresses or name locals and constants
(no call, no load): different members never share bytes, so either order is the same program. The whole-path audit
of a KMC N64 game's matched functions (docs/learnings in decompdecomp) found a list-building loop stuck at 20 with
only this swap left (20 -> 0).
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'adjacent_array_store_order'
FAMILIES = (FAMILY,)
LIMIT = 40
STORE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<array>{IDENT})\[\s*(?P<index>{NUMBER})\s*\]\s*=(?!=)\s*(?P<value>[^;{{}}]*);[ \t]*\n')


ELEMENT = re.compile(rf'(?P<array>{IDENT})\[(?P<index>[^\[\];{{}}]+)\]\s*\.\s*(?P<field>{IDENT})\s*=(?!=)\s*'
                     rf'(?P<value>[^;{{}}]*);')
GAP = re.compile(r'[ \t]*\n?[ \t]*')
# a value with no load: an address (`&D[i - 1]`), a name, a number, and arithmetic of them
ADDRESS = re.compile(rf'&\s*{IDENT}(?:\s*\[[^\[\];]*\])?(?:\s*\.\s*{IDENT})*')
PLAIN = re.compile(rf'^(?:{IDENT}|{NUMBER}|[\s+\-*()]|0x[0-9a-fA-F]+)*$')


def _no_load(value):
    rest = ADDRESS.sub('0', value)
    return bool(PLAIN.match(rest)) and '*' not in rest.replace(' * ', '+')


def element_field_variants(source, name):
    """Two adjacent stores to different fields of one array's elements, swapped (module docstring)."""
    part = view(source, name)
    if not part:
        return []
    result = []
    for first in ELEMENT.finditer(part.clean, part.opening, part.end):
        gap = GAP.match(part.clean, first.end())
        second = ELEMENT.match(part.clean, gap.end())
        if (not second or second.end() > part.end or second['array'] != first['array']
                or second['field'] == first['field'] or not _no_load(first['value'])
                or not _no_load(second['value']) or re.search(rf'\b{IDENT}\s*\(', first['value'] + second['value'])):
            continue
        a, b = source[first.start():first.end()], source[second.start():second.end()]
        text = b + source[first.end():second.start()] + a
        result.append((FAMILY, edit(source, [(first.start(), second.end(), text)])))
        if len(result) >= LIMIT:
            break
    return result


def variants(source, name):
    return _array_variants(source, name) + element_field_variants(source, name)


def _array_variants(source, name):
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

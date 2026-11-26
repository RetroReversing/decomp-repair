"""A member stepped and wrapped back into range, with the stepped value read again before the test.

An N64 object update (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`, 93 instructions) steps an angle in a record,
`rec->angle += 1.0f;`, and wraps it, `if (angle > 360.0f) angle -= 360.0f;`. The target loads the member again after the
store, compares that and subtracts from the same register; the compiler forwards the stored value instead for the plain
statements (315). Declaring the member `volatile` alone reloads it twice (300), and a local for the compared value alone
changes nothing (315); both together were byte-identical. The exact judge cannot say how the original was spelled (reading
the member through a second symbol of the same address also matched), so this is one spelling that gives its code.

`wrap_reread_member`
    For each `L += K; if (L > C) { L -= C2; }` (any of the four comparisons, `+=` or `-=`) where `L` ends in a struct
    member the source declares once with a plain arithmetic type: `L += K; v = L; if (v > C) { L = v - C2; }` with a
    local `v` of that type. Children, in order: the member also declared `volatile`; the local alone.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'wrap_reread_member'
FAMILIES = (FAMILY,)
TYPES = r'(?:f32|f64|float|double|u8|s8|u16|s16|u32|s32|int|short|char)'
LVALUE = r'(?P<l>' + IDENT + r'(?:\s*\[[^\[\];{}]*\]|\s*(?:\.|->)\s*' + IDENT + r')*\s*(?:\.|->)\s*(?P<member>' + IDENT + r'))'
VALUE = r'[\w.]+'
SHAPE = re.compile(
    r'(?<=[;{}])(?P<lead>\s*)' + LVALUE + r'\s*(?P<step>[+-])=\s*(?P<k>' + VALUE + r')\s*;'
    r'(?P<gap>\s*)if\s*\(\s*(?P=l)\s*(?P<compare>[<>]=?)\s*(?P<c>-?' + VALUE + r')\s*\)\s*'
    r'(?P<open>\{\s*)?(?P=l)\s*(?P<back>[+-])=\s*(?P<c2>' + VALUE + r')\s*;(?(open)\s*\})')


def variants(source, name):
    part = view(source, name)
    if not part or not find(source, name):
        return []
    clean = part.clean
    results = []
    for hit in SHAPE.finditer(clean, part.opening, part.end):
        member = hit['member']
        declared = list(re.finditer(r'(?<=[;{}])\s*(?P<qualifier>volatile\s+)?(?P<type>' + TYPES + r')\s+'
                                    + member + r'\s*;', clean[:part.opening]))
        if len(declared) != 1 or declared[0]['qualifier']:
            continue
        local = 'stepped'
        while re.search(r'\b' + local + r'\b', source):
            local += '_'
        left = source[hit.start('l'):hit.end('l')]
        indent = hit['lead'][hit['lead'].rfind('\n') + 1:]
        text = (f'{left} {hit["step"]}= {hit["k"]};\n{indent}{local} = {left};\n'
                f'{indent}if ({local} {hit["compare"]} {hit["c"]}) {{\n'
                f'{indent}    {left} = {local} {hit["back"]} {hit["c2"]};\n{indent}}}')
        kind = declared[0]['type']
        edits = [(part.opening + 1, part.opening + 1, f'\n    {kind} {local};'), (hit.start('l'), hit.end(), text)]
        at = declared[0].start('type')
        results.append((FAMILY, edit(source, [(at, at, 'volatile ')] + edits)))
        results.append((FAMILY, edit(source, edits)))
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}  # the registry: no caller wiring (registry.py)

"""A round-up to a power of two written back into its own variable, as the three statements the game's compiler saw.

`size = ((u32) (size + 0xF) >> 4) * 0x10;` and `size += 0xF; size >>= 4; size <<= 4;` are the same program, but GCC 2.x
expands the first through temporaries of its own, while the second keeps every step in the variable's register: an N64
asset loader (sn-n64-281 GCC 2.8.1, `-mfp64`, 229 instructions) sat at 15 with the one expression and was exact with the
three statements. One result per function, so why the compiler wants it is a hypothesis.

`variants` finds `X = ((u32) (X + K) >> N) << N;` (or `* (1 << N)` written as the number), `X` a plain local or parameter,
with the shift unsigned (the `(u32)` cast, or `X` declared `u32`). One child per site, and one with all of them.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view

FAMILY = 'round_up_in_steps'
FAMILIES = (FAMILY,)
LIMIT = 6
NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
CAST = r'(?:\(\s*u32\s*\)\s*)'
STATEMENT = re.compile(
    rf'(?<![\w.>])(?P<x>{IDENT})\s*=\s*(?P<outer>{CAST})?\(\s*(?P<cast>{CAST})?\(\s*(?:{CAST})?(?:\(\s*)?(?:{CAST})?'
    rf'(?:\(\s*(?P=x)\s*\)|(?P=x))\s*\+\s*(?P<k>{NUMBER})\s*\)(?:\s*\))?\s*>>\s*(?P<n>{NUMBER})\s*\)\s*'
    rf'(?P<op><<|\*)\s*(?P<back>{NUMBER})\s*;')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = _blank(source)
    edits = []
    for hit in STATEMENT.finditer(clean, part.opening, part.end):
        shift, back = int(hit['n'], 0), int(hit['back'], 0)
        if back != (shift if hit['op'] == '<<' else 1 << shift):
            continue
        matched = hit.group(0)
        if matched.count('(') != matched.count(')'):
            continue
        x = hit['x']
        if 'u32' not in matched and not re.search(rf'\bu32\s+{x}\b', clean[:hit.end()]):
            continue
        if not re.search(r'(?:\A|[;{}:])\s*\Z', clean[:hit.start()]):
            continue
        line = source.rfind('\n', 0, hit.start()) + 1
        indent = source[line:hit.start()]
        joint = f'\n{indent}' if not indent.strip() else ' '
        steps = joint.join([f'{x} += {hit["k"]};', f'{x} >>= {shift};', f'{x} <<= {shift};'])
        # a signed variable keeps its logical shift only through the cast
        if not re.search(rf'\bu32\s+{x}\b', clean[:hit.end()]):
            steps = joint.join([f'{x} += {hit["k"]};', f'{x} = (u32) {x} >> {shift};', f'{x} <<= {shift};'])
        edits.append((hit.start(), hit.end(), steps))
    out = [(FAMILY, edit(source, [one])) for one in edits[:LIMIT]]
    if len(edits) > 1:
        out.insert(0, (FAMILY, edit(source, edits)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 900}

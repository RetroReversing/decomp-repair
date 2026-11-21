"""A record field stored next to a scalar global, written as a raw offset store so the scheduler keeps their order.

gcc 2.7.2 decides whether two memory references may conflict partly by MEM_IN_STRUCT_P: a reference through a
structure member is "in struct", a fixed-address scalar global is not, and alias.c treats that pair as never
conflicting. So `cur->pos = -1;` beside `G = b;` lets the first scheduling pass move the global's store across the
field store, while `*(s16 *)((u8 *)cur + 0x12) = -1;` (no structure, so the same class as the global) keeps the
order the C wrote. In an N64 four-case switch (KMC gcc 2.7.2) the two cursor stores right after a global flag store
had to be written that way (420 to 340); every field store of the function written raw scored far worse (1070), so
this offers only the stores within a couple of statements of a scalar global's store: each one alone, and all of
them together. The layout comes from a `typedef struct` in the file or header whose members' sizes are all known
(compiler_shape_repairs.fields), so the offset is the one the compiler computes; the judge decides the rest.
"""
import re

from .compiler_shape_repairs import fields
from .integer_repair_support import IDENT, edit, view

FAMILY = 'struct_store_raw_offset'
FAMILIES = (FAMILY,)
NEAR = 2  # statements between a field store and the global's store
LIMIT = 8
STORE = re.compile(rf'(?m)^[ \t]*(?P<var>{IDENT})\s*->\s*(?P<member>{IDENT})\s*(?P<op>(?:[-+*/|&^]|<<|>>)?=)(?!=)[^;]*;')
GLOBAL = re.compile(rf'(?m)^[ \t]*(?P<name>{IDENT})\s*(?:[-+*/|&^]|<<|>>)?=(?!=)[^;]*;')


def _statements(body):
    """(start, end, text) of each simple statement line in the body, in order; braces end a run."""
    out = []
    for line in re.finditer(r'(?m)^[^\n]*$', body):
        text = line.group().strip()
        if text:
            out.append((line.start(), line.end(), text))
    return out


def variants(source, name, header=''):
    if not (part := view(source, name)):
        return []
    layout = {}
    for record, typ, member, offset in fields(header + '\n' + source[:part.opening]):
        layout.setdefault(record, {})[member] = (typ, offset)
    if not layout:
        return []
    body, base = part.clean[part.opening + 1:part.end], part.opening + 1
    signature = part.clean[max(part.clean.rfind(ch, 0, part.opening) for ch in ';}') + 1:part.opening]
    pointers = {m[2]: m[1] for m in re.finditer(rf'\b({IDENT})\s*\*\s*({IDENT})\s*(?=[,;=)])', signature + '\n' + body)
                if m[1] in layout}
    local = set(re.findall(rf'\b{IDENT}\s+\**\s*({IDENT})\s*[;=,)\[]', signature + '\n' + body))
    context = header + '\n' + part.clean[:part.opening]
    scalars = {m[1] for m in re.finditer(rf'\bextern\s+(?:volatile\s+)?(?:[su](?:8|16|32)|f32|int|short|char|'
                                         rf'unsigned\s+\w+)\s+({IDENT})\s*;', context)} - local
    lines = _statements(body)
    near_global = [i for i, (_, _, text) in enumerate(lines)
                   if (g := GLOBAL.match(text)) and g['name'] in scalars]
    sites = []
    for i, (start, end, text) in enumerate(lines):
        hit = STORE.match(text)
        if not hit or hit['var'] not in pointers or hit['member'] not in layout[pointers[hit['var']]]:
            continue
        if not any(0 < abs(i - g) <= NEAR and not any('{' in lines[k][2] or '}' in lines[k][2]
                                                      for k in range(min(i, g), max(i, g) + 1) if k not in (i, g))
                   for g in near_global):
            continue
        typ, offset = layout[pointers[hit['var']]][hit['member']]
        if typ.endswith('*'):
            continue
        at = body.index(text, start)
        lhs = re.match(rf'{IDENT}\s*->\s*{IDENT}', text)
        sites.append((base + at, base + at + lhs.end(), f'*({typ} *)((u8 *){hit["var"]} + 0x{offset:X})'))
    out = []
    if len(sites) > 1:
        out.append((FAMILY, edit(source, sites)))
    out += [(FAMILY, edit(source, [site])) for site in sites]
    return out[:LIMIT]

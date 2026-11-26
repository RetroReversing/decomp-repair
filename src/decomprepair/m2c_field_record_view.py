"""m2c's `M2C_FIELD(p, T *, K)` accesses written as members of a record type for `p`.

m2c prints every field it has no type for as `M2C_FIELD(arg0, s32 *, 0x88)`, a cast and an add. The game declared a
struct, and the compiler treats the two differently: a member access is a structure reference, which the scheduler and
cse can tell apart from a store through another pointer. A stuck N64 function matched only once its raw casts became
members (see byte_pointer_record_view, which reads hand-written casts; this reads m2c's own macro). Measured on 80
fresh m2c drafts of matched functions of an SN64 GCC 2.8.1 game, judged beside the plain draft: 21 scored lower with
records (3 of them exact), 2 higher, 57 the same, and none stopped compiling. Candidates to judge, never a replacement.

Children: every pointer retyped, then each pointer on its own when there are several. A base is retyped only when it is
a plain name, each offset is read with one type, no two members overlap and every offset is a multiple of its member's
size. Pointer members are `void *`. Only the function's own accesses are rewritten.
"""
import re

FAMILY = 'm2c_field_record_view'
FAMILIES = (FAMILY,)
SIZES = {'s8': 1, 'u8': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4, 'f32': 4, 's64': 8, 'u64': 8, 'f64': 8,
         'M2C_UNK': 4, 'M2C_UNK8': 1, 'M2C_UNK16': 2, 'M2C_UNK32': 4}
POINTER = 4  # the targets m2c drafts for here have 32-bit pointers
FIELD = re.compile(r'\bM2C_FIELD\(\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*(\*+)\s*,\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\s*\)')
MAX_BASES = 8


def _definition(source, name):
    """Where the function's definition starts (its line), or None."""
    found = re.search(r'^[^\n#;]*\b' + re.escape(name) + r'\s*\([^;{}]*\)\s*\{', source, re.M)
    return found.start() if found else None


def _layouts(body):
    """{base: {offset: (member type, size)}} for the bases that can be records."""
    seen, refused = {}, set()
    for match in FIELD.finditer(body):
        base, typ, stars, offset = match[1], match[2], match[3], int(match[4], 0)
        member, size = ('void *', POINTER) if len(stars) > 1 else (typ, SIZES.get(typ))
        fields = seen.setdefault(base, {})
        if size is None or offset < 0 or offset % size or fields.setdefault(offset, (member, size)) != (member, size):
            refused.add(base)
    out = {}
    for base, fields in seen.items():
        ordered = sorted(fields.items())
        if base not in refused and all(at + size <= later for (at, (_, size)), (later, _) in zip(ordered, ordered[1:])):
            out[base] = dict(ordered)
    return out


def _record(tag, fields):
    lines, at = [], 0
    for offset, (member, size) in fields.items():
        if offset > at:
            lines.append(f'    char pad{at:X}[0x{offset - at:X}];')
        space = '' if member.endswith('*') else ' '
        lines.append(f'    {member}{space}m{offset:X};')
        at = offset + size
    return 'typedef struct {\n' + '\n'.join(lines) + f'\n}} {tag};\n'


def _members(body, base, tag):
    return FIELD.sub(lambda m: f'((({tag} *) {base})->m{int(m[4], 0):X})' if m[1] == base else m[0], body)


def _child(source, name, start, bases):
    head, body = source[:start], source[start:]
    records = []
    for base, fields in bases.items():
        tag = f'Rec_{name}_{base}'
        if re.search(r'\b' + re.escape(tag) + r'\b', source):
            return None
        records.append(_record(tag, fields))
        body = _members(body, base, tag)
    return head + ''.join(records) + '\n' + body


def variants(source, name):
    start = _definition(source, name)
    if start is None or 'M2C_FIELD(' not in source:
        return []
    layouts = _layouts(source[start:])
    if not layouts:
        return []
    choices = [layouts]
    if len(layouts) > 1:
        choices += [{base: fields} for base, fields in list(layouts.items())[:MAX_BASES]]
    children = (_child(source, name, start, bases) for bases in choices)
    return [(FAMILY, child) for child in children if child and child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring

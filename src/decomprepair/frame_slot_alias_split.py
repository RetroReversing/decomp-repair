"""A frame slot read as a plain scalar and the stores through pointers written as record members, so the read moves up.

sched.c (`true_dependence`) lets a load pass an earlier store when one of them is a `MEM_IN_STRUCT` reference at a varying
address of a word or halfword and the other is not `MEM_IN_STRUCT` and sits at a fixed address ("A MEM_IN_STRUCT reference
at a non-QImode varying address can never conflict with a non-MEM_IN_STRUCT reference at a fixed address"). A draft names
its stack slots as members of one local struct (`locals.sp40`, the frame view `m2c_spelling.plain` writes out) and stores
through pointers as `*(s32 *)((char *)p + 0x34) = v;`: the load is the struct reference and the store is the plain one,
which is the one pairing that always conflicts. The scheduler then keeps the store ahead of the load, the store's result
register stays live across the slot's whole test, and the temporaries take `$v1`, `$a0` and the saved registers the target
does not.

The rewrite reads each non-byte member as `*(T *)((char *)&locals + OFFSET)` (a plain dereference at the frame's fixed
address; the offsets are the struct's own layout) and writes each store through a pointer variable that has a word or
halfword member at its offset (`((__repair_rec_52_s32 *) p)->f = v;`, the record `char pad[52]; s32 f;` declared before
the function), both at once: either half alone moves nothing (3301 -> 3301 twice) and together they scored 3301 -> 3021 on
an 874-instruction KMC N64 object spawner (`-G0 -mips3 -mgp32 -mfp32 -O2`, the two `sp40` tests of its record allocator
and eight stores, the exact judge). The reading is from sched.c's comment and the dependence list the dump printed
(`insn_list 635` on the load); the judge decides, and no child is a verdict.

`variants` takes the function's frame struct (an anonymous local struct whose members are all fixed-size integers,
floats, pointers and byte arrays), skips a member whose address is taken for a read, and offers the pair as one child.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'frame_slot_alias_split'
FAMILIES = (FAMILY,)
_SIZES = {'s8': 1, 'u8': 1, 'char': 1, 'signed char': 1, 'unsigned char': 1, 's16': 2, 'u16': 2, 'short': 2,
          'unsigned short': 2, 's32': 4, 'u32': 4, 'int': 4, 'unsigned': 4, 'unsigned int': 4, 'f32': 4, 'float': 4}
_STRUCT = re.compile(rf'struct\s*{{(?P<body>[^{{}}]*)}}\s*(?P<var>{IDENT})\s*;')
_STORE = re.compile(rf'\*\(\((?P<type>(?:unsigned\s+)?{IDENT})\s*\*\)\s*\(\(\(char\s*\*\)\s*(?P<ptr>{IDENT})\)\s*\+\s*'
                    rf'(?P<offset>0x[0-9A-Fa-f]+|\d+)\)\)(?P<op>\s*(?:[-+|&^]|<<|>>)?=(?!=))')


def _members(body):
    """{member: (type, offset)} of a frame struct's members in their natural layout, or None when one is not plain."""
    found, at = {}, 0
    for declaration in body.split(';'):
        text = ' '.join(declaration.split())
        if not text:
            continue
        match = re.match(rf'(?P<type>(?:unsigned\s+|signed\s+)?{IDENT}(?:\s+int)?)\s+(?P<names>.+)$', text)
        if not match or match['type'] not in _SIZES:
            return None
        size = _SIZES[match['type']]
        for piece in match['names'].split(','):
            name = re.fullmatch(rf'\s*({IDENT})\s*(?:\[\s*(\d+)\s*\])?\s*', piece)
            if not name:
                return None
            at = -(-at // size) * size
            found[name[1]] = (match['type'], at)
            at += size * int(name[2] or 1)
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    frame = _STRUCT.search(clean, part.opening, part.end)
    if not frame:
        return []
    var = frame['var']
    members = _members(frame['body'])
    if not members:
        return []
    changes, records = [], {}
    for hit in re.finditer(rf'(?<![&\w.>])(?P<var>{re.escape(var)})\.(?P<member>{IDENT})\b', clean[frame.end():part.end]):
        start = frame.end() + hit.start()
        member = hit['member']
        kind, offset = members.get(member, (None, 0))
        after = clean[frame.end() + hit.end():part.end]
        if kind is None or _SIZES[kind] == 1 or re.match(r'\s*(?:[-+|&^*/%]|<<|>>)?=(?!=)|\s*(?:\+\+|--)', after):
            continue
        before = clean[:start].rstrip()
        if before.endswith(('++', '--')):
            continue
        changes.append((start, frame.end() + hit.end(), f'(*({kind} *)((char *)&{var} + {offset}))'))
    reads = len(changes)
    for hit in _STORE.finditer(clean, frame.end(), part.end):
        kind, pointer, offset = hit['type'], hit['ptr'], int(hit['offset'], 0)
        size = _SIZES.get(kind)
        if not size or size == 1 or offset % size or pointer == var:
            continue
        record = f'__repair_rec_{offset}_{kind.replace(" ", "_")}'
        records[record] = f'typedef struct {{ char pad[{offset}]; {kind} f; }} {record};\n'
        changes.append((hit.start(), hit.end(), f'(({record} *) {pointer})->f{hit["op"]}'))
    if not reads or len(changes) == reads:
        return []
    start = find_start(part, name)
    typedefs = ''.join(records.values())
    return [(FAMILY, edit(source, changes + [(start, start, typedefs)]))]


def find_start(part, name):
    """Where the function's definition begins: the line that holds its name and `(` before the opening brace."""
    head = part.source[:part.opening]
    at = head.rfind(name)
    return head.rfind('\n', 0, at) + 1


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)

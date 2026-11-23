"""A frame slot written as a plain scalar beside the pointer accesses next to it written as record members.

`frame_slot_alias_split` moves frame *reads* past pointer stores. The same rule of sched.c (`true_dependence` and
`anti_dependence`: a `MEM_IN_STRUCT` reference at a varying address of a word or halfword never conflicts with a
non-`MEM_IN_STRUCT` one at a fixed address) decides the order of a frame slot's *write* and the pointer load or store
beside it. A draft's `locals.sp30 = 1;` is a struct member at a fixed address and `x = *(void **)((char *)p + 0x3C);` a
plain dereference at a varying one: the pairing that always conflicts, so the scheduler keeps the source order.

On an 874-instruction KMC N64 object spawner (`-G0 -mips3 -mgp32 -mfp32 -O2`) `temp_s4 = *(void **)((char *)*arg0 +
0x3C); locals.sp30 = 1; clear(&D);` kept the load ahead of the store and the call's delay slot held the store; the
target puts the load in the delay slot. Written `temp_s4 = ((__repair_rec_60_s32 *) *arg0)->f;` and
`*(s32 *)((char *)&locals + 0) = 1;` the order flips and the allocation after it with it (3021 -> 2756, each half alone
3021). The two halves are one child.

`variants` takes each statement that writes a word or halfword member of the function's frame struct and, beside it, the
statement before and the statement after (in the same block) that dereference a pointer variable (or `*variable`) at a
constant offset: one child writes the slot as `*(T *)((char *)&locals + OFFSET)` and the neighbour's dereferences as
members of a `char pad[OFFSET]; T f;` record declared before the function; one child per neighbour, one for both. The judge
decides, and no child is a verdict.
"""
import re

from .frame_slot_alias_split import _SIZES, _STRUCT, _members, find_start
from .integer_repair_support import IDENT, edit, view
from .run_weight_scope import _block_statements, _inner

FAMILY = 'frame_write_alias_split'
FAMILIES = (FAMILY,)
_ACCESS = re.compile(rf'\*\(\((?P<type>(?:unsigned\s+)?{IDENT}(?:\s*\*)*)\s*\*\)\s*\(\(\(char\s*\*\)\s*(?P<ptr>{IDENT}|\(\*{IDENT}\))\)\s*\+\s*'
                     rf'(?P<offset>0x[0-9A-Fa-f]+|\d+)\)\)')


def _typed(source, text_start, text, frame_var):
    """[(start, end, replacement, record, typedef)] for each dereference at a constant offset inside `text`."""
    found = []
    for hit in _ACCESS.finditer(text):
        kind, pointer, offset = ' '.join(hit['type'].split()), hit['ptr'], int(hit['offset'], 0)
        size = 4 if kind.endswith('*') else _SIZES.get(kind)
        if not size or size == 1 or offset % size or pointer == frame_var:
            continue
        record = f'__repair_rec_{offset}_{kind.replace(" ", "_").replace("*", "p")}'
        typedef = f'typedef struct {{ char pad[{offset}]; {kind} f; }} {record};\n'
        found.append((text_start + hit.start(), text_start + hit.end(), f'(({record} *) {pointer})->f', record, typedef))
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    frame = _STRUCT.search(clean, part.opening, part.end)
    members = _members(frame['body']) if frame else None
    if not members:
        return []
    var = frame['var']
    write = re.compile(rf'(?<![&\w.>])(?P<var>{re.escape(var)})\.(?P<member>{IDENT})(?P<op>\s*(?:[-+|&^]|<<|>>)?=(?!=))')
    result, seen = [], set()
    for start, end in sorted(set(_inner(clean, frame.end(), part.end - 1))):
        listed = _block_statements(clean, start, end)
        for index, (a, b, compound) in enumerate(listed):
            hit = write.match(clean[a:b].lstrip(), 0)
            if compound or not hit:
                continue
            kind, offset = members.get(hit['member'], (None, 0))
            if kind is None or _SIZES[kind] == 1:
                continue
            slot = (a + len(clean[a:b]) - len(clean[a:b].lstrip()), None)
            lead = a + len(clean[a:b]) - len(clean[a:b].lstrip())
            plain = (lead, lead + hit.end(), f'(*({kind} *)((char *)&{var} + {offset})){hit["op"]}')
            options = []
            for neighbour in (index - 1, index + 1):
                if 0 <= neighbour < len(listed) and not listed[neighbour][2]:
                    c, d, _ = listed[neighbour]
                    options.append(_typed(source, c, clean[c:d], var))
            options = [o for o in options if o]
            choices = [[o] for o in options] + ([options] if len(options) == 2 else [])
            for choice in choices:
                accesses = [x for group in choice for x in group]
                key = (lead, tuple(sorted((x[0], x[1]) for x in accesses)))
                if key in seen:
                    continue
                seen.add(key)
                typedefs = ''.join({x[3]: x[4] for x in accesses if f'}} {x[3]};' not in source}.values())
                edits = [plain] + [(x[0], x[1], x[2]) for x in accesses]
                edits = [(x[0], x[1], x[2]) for x in edits]
                at = find_start(part, name)
                result.append((FAMILY, edit(source, edits + [(at, at, typedefs)])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)

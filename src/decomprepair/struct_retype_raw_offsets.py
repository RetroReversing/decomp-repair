"""Raw `M2C_FIELD(p, T *, off)` accesses of one pointer retyped as the members of ONE struct.

GCC 2.8 (like 2.7.2, `struct_store_raw_offset`) decides whether two memory references may conflict partly by whether
each is "in a struct": a member of a record reached through a pointer is, a fixed-address global is not, and the two
never alias. So `p->f10 = x; G = y;` may be scheduled in either order across the other and loads through `p` move above
a store to `G`, where the raw `*(T *)((s8 *)p + 0x10)` of m2c is "unknown" and keeps every store and load in place.
`field_struct_view` redefines the macro with a one-member record per access; the originals had ONE record for the
pointer, so every access shares a type (accesses through two different one-member records of a pointer are different
alias sets to nothing, but they are different MEM expressions to the scheduler's address comparison). Hand matches on SN
GCC 2.8.1 N64 code moved their loads and stores to the target's places only with a single struct for the pointer
(six functions: a field read above a store to a global, a store sunk past a load, a packet writer's stores in order).

For each pointer variable `p` (a plain identifier) that the function reads or writes through `M2C_FIELD(p, T *, 0xOFF)`
at two or more distinct offsets, with T a scalar of 1, 2 or 4 bytes (`s8`..`u32`, `f32`, `M2C_UNK*`) or any pointer type,
every access at a naturally aligned offset that overlaps no other member, the child writes

    typedef struct { u8 pad_0[0x10]; s32 f10; f32 f14; } PtrRec_p;

before the function (explicit padding between members, so the offsets are exact) and rewrites each access to
`((PtrRec_p *) p)->f10`. Gates: the function also touches a global (a bare `D_`/`g`-style symbol of the file) and
stores through `p`, since the rewrite is about ordering against fixed addresses; One child per pointer (at most `LIMIT`) and one with all of them.
An access the record cannot hold (unaligned, two types at one offset, or overlapping a more used member: m2c's `u16`
read of the low half at 0x12 of an `s32` at 0x10) keeps its raw `M2C_FIELD` and the others are still members, so long
as two remain. Until 0.6.14 such an access skipped the pointer altogether: a 1,389-instruction SN N64 state machine whose
`arg0` had one such halfword was offered nothing, and the hand-written record took it from 1695 to 1635 (and, with
the scheduling it then allowed, to a match). A function with `volatile` or `asm`, or whose `p` is also taken by address,
is skipped. The reverse for single stores that must not move is `struct_store_raw_offset`. Proposals only; the judge decides."""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'struct_retype_raw_offsets'
FAMILIES = (FAMILY,)
LIMIT = 4
_WIDTH = {'s8': 1, 'u8': 1, 'char': 1, 'M2C_UNK8': 1, 's16': 2, 'u16': 2, 'short': 2, 'M2C_UNK16': 2,
          's32': 4, 'u32': 4, 'f32': 4, 'int': 4, 'float': 4, 'long': 4, 'M2C_UNK': 4, 'M2C_UNK32': 4}
_ACCESS = re.compile(rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*(?P<type>[^,()]+?)\s*\*\s*,\s*(?P<off>0[xX][0-9a-fA-F]+|\d+)\s*\)')
_GLOBAL = re.compile(r'(?<![\w.>])(?:D_[0-9A-Fa-f]{6,8}|g[A-Z]\w*)\b')


def _member(kind, pointers=()):
    """(member type text, width) of the element a `T *` access points at, or None."""
    kind = re.sub(r'\bconst\b', '', kind).strip()
    if kind.endswith('*'):
        return kind, 4  # a pointer member: `void **` as a `void *` member
    if kind in pointers:
        return kind, 4  # a function-pointer typedef
    return (kind, _WIDTH[kind]) if kind in _WIDTH else None


def _layout(accesses, pointers=()):
    """([(offset, member type, width)] sorted, offsets kept raw), or None when fewer than two members remain.

    An access the record cannot hold (unaligned, a second type at one offset, or one overlapping a member, like the
    `u16` low half at 0x12 of the `s32` at 0x10) stays raw; members are chosen by how often each offset is accessed,
    so the halfword read twice gives way to the word read five times."""
    shapes, counts, raw = {}, {}, set()
    for offset, kind in accesses:
        shape = _member(kind, pointers)
        if not shape or offset % shape[1] or shapes.setdefault(offset, shape) != shape:
            raw.add(offset)
        counts[offset] = counts.get(offset, 0) + 1
    kept = {}
    for offset in sorted((o for o in shapes if o not in raw), key=lambda o: (-counts[o], o)):
        width = shapes[offset][1]
        if all(offset + width <= other or other + kept[other][1] <= offset for other in kept):
            kept[offset] = shapes[offset]
        else:
            raw.add(offset)
    if len(kept) < 2:
        return None
    return [(offset, *kept[offset]) for offset in sorted(kept)], raw


def _record(name, fields):
    lines, at = [], 0
    for offset, kind, width in fields:
        if offset > at:
            lines.append(f'u8 pad_{at:X}[0x{offset - at:X}];')
        lines.append(f'{kind} f{offset:X};')
        at = offset + width
    return 'typedef struct { ' + ' '.join(lines) + f' }} {name};\n'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|asm|__asm__)\b', body):
        return []
    per = {}
    for hit in _ACCESS.finditer(part.clean, part.opening, part.end):
        per.setdefault(hit['base'], []).append((hit, int(hit['off'], 0), hit['type']))
    outside = part.clean[:part.opening] + part.clean[part.end:]
    stores = lambda base: re.search(rf'M2C_FIELD\(\s*{re.escape(base)}\s*,[^;=]*?\)\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', body)
    touches_global = bool(_GLOBAL.search(body))
    pointers = set(re.findall(rf'typedef[^;{{}}]*\(\s*\*\s*({IDENT})\s*\)\s*\(', source))
    children, found = [], []
    for base in sorted(per):
        items = per[base]
        if len({o for _, o, _ in items}) < 2 or re.search(rf'&\s*{re.escape(base)}\b', body):
            continue
        if not (touches_global and stores(base)):
            continue
        shaped = _layout([(o, k) for _, o, k in items], pointers)
        if not shaped:
            continue
        layout, raw = shaped
        record = f'PtrRec_{base}'
        if re.search(rf'\b{record}\b', outside):
            continue
        spans = [(h.start(), h.end(), f'(({record} *) {base})->f{o:X}') for h, o, _ in items if o not in raw]
        found.append((base, record, layout, spans))
    start = source.rfind('\n', 0, find(source, name)[0]) + 1
    for base, record, layout, spans in found[:LIMIT]:
        children.append((FAMILY, edit(source, spans + [(start, start, _record(record, layout))])))
    if len(found) > 1:
        edits = [s for *_, spans in found for s in spans] + [(start, start, ''.join(_record(r, l) for _, r, l, _ in found))]
        children.append((FAMILY, edit(source, edits)))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}

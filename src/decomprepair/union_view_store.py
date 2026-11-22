"""A float stored as a word through a block-scoped union, written as the plain float store.

m2c writes a float that a decompiled `sw` stores as an integer through a union view:

    { union { f32 f; int i; } v; v.f = value; *(int *)((char *)arg0 + 4) = v.i; }

The compiler writes the same instructions for the plain `*(f32 *)((char *)arg0 + 4) = value;`: the target of a
4x4 rotation-matrix builder (KMC GCC 2.7.2) has `mfc1 $v0,$f14; sw $v0,4($s0)` for a field the source stores as a
float, not because the source punned it (hypothesis: the allocator reloaded the product through an integer register).
The union is not free, and this one is read from the compiler's source (sched.c): the union's destination is a
`subreg` of an integer pseudo, and the first scheduler raises an insn's priority only when its destination is a plain
register set once (`birthing_insn_p`, `adjust_priority`), so a product written into the union is scheduled before every
other product, where the target has it fourth. With the plain float
store the matrix builder went 160 -> 0 together with the store order and two shared-product temporaries.

Children: each union store as the plain float store, one at a time, and every one at once (when there are several). The
write is the same bytes either way: a float store of the value the union held.

The plain store alone did not move the matrix builder (15 before and after): the other product that was scheduled
out of place was a product two stores shared, `(x * y) * z - a` and `(x * y) * w + b`, which the target holds in one
register for both; naming it (`t = x * y;`, used in both) did not move it alone either, and the two together went
15 -> 0. So `union_view_store_plain_shared` offers the plain stores together with each temporary_hoist child that names
a sub-expression the statements use more than once (the temporary used at least twice), bounded.
"""
import re

from .csource import _blank, find
from .offset_store_order import UNION
from .pattern_repairs import close

FAMILY = 'union_view_store_plain'
FAMILY_SHARED = 'union_view_store_plain_shared'
FAMILIES = (FAMILY, FAMILY_SHARED)
SHARED_LIMIT = 8
FLOAT = {'f32', 'float'}
INTEGER = {'int', 's32', 'u32', 'unsigned', 'unsigned int', 'long', 'signed int'}


def _blocks(source, clean, start, end):
    """(begin, stop, replacement) of each union-view store of a float as a word in clean[start:end]."""
    found = []
    for hit in re.finditer(r'\{\s*union\b', clean[start:end]):
        position = start + hit.start()
        match = UNION.match(source, position)
        if not match:
            continue
        first, f1, second, f2, var, written, value, kind, base, offset, read = match.groups()
        types = {f1: first.strip(), f2: second.strip()}
        if written == read or types[written] not in FLOAT or types[read] not in INTEGER or ' '.join(kind.split()) not in INTEGER:
            continue
        if re.search(rf'(?<![\w.]){re.escape(var)}\b', value):
            continue
        address = f'(char *){base}' + (f' + {offset}' if offset else '')
        found.append((match.start(), match.end(), f'*({types[written]} *)({address}) = {value.strip()};'))
    return found


def variants(source, name):
    part = find(source, name)
    if not part:
        return []
    clean = _blank(source)
    definition = re.search(r'\b' + re.escape(name) + r'\s*\([^{};]*\)\s*{', clean[part[0]:part[1]])
    if not definition:
        return []
    opening = part[0] + definition.end() - 1
    end = close(clean, opening, '{', '}') or part[1]
    blocks = _blocks(source, clean, opening + 1, end - 1)
    result = []
    for begin, stop, text in blocks:
        result.append((FAMILY, source[:begin] + text + source[stop:]))
    done = source
    for begin, stop, text in reversed(blocks):
        done = done[:begin] + text + done[stop:]
    if len(blocks) > 1:
        result.append((FAMILY, done))
    if blocks:
        result += _shared(done, name)
    return result


def _shared(plain, name):
    """The plain-store source with each temporary_hoist child that names a sub-expression used at least twice."""
    from . import temporary_hoist_repairs

    declared = set(re.findall(r'\b(\w+)\s*[;,]', plain))
    kept = []
    for item in temporary_hoist_repairs.variants(plain, name):
        text = item[1] if isinstance(item, tuple) else item
        if text == plain:
            continue
        added = set(re.findall(r'\bf32\s+(\w+)\s*;', text)) - declared
        for local in added:
            uses = len(re.findall(rf'(?<![\w.]){re.escape(local)}\b', text)) - 2
            if uses >= 2:
                kept.append((FAMILY_SHARED, text))
                break
        if len(kept) == SHARED_LIMIT:
            break
    return kept


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

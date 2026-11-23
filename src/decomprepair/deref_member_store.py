"""A store through a pointer variable, `*p = v;`, written as a member of a one-member record.

gcc 2.7.2's scheduler decides whether a store and a later load may swap from their kinds (sched.c, `true_dependence`
in rtlanal.c): a reference through a structure member at a varying address ("in struct", `MEM_IN_STRUCT_P`) never
conflicts with a reference at a fixed address that is not in a structure, while a plain `*p` store and a global's read
always may. m2c writes `*D_P = 0;` for a store through a pointer the game kept in a record, so the global read after
it waits behind the store in the first scheduler and the order of the two (and the registers that follow from it) comes
out the other way round from the target, which loads the global first and stores in the branch's delay slot. This is
the member_alias_pair rule for a raw-offset word, applied to the plain dereference of a global or local pointer.

`variants` offers, for a store statement `*P = v;` (P an `extern T *P;` global or a `T *P;` local, T an integer type up
to a word) with a read of a plain scalar global in the next few lines of the same block, the store written
`((__repair_deref_T *) P)->value = v;` with `typedef struct { T value; } __repair_deref_T;` declared before the
function: one child per such store and one with all of them. Measured on a 370-instruction mixing-buffer function
(KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): the store through the pointer the previous line had just loaded, then
`if (D_800E4268 != limit)`, 1680 -> 1610 alone and 1560 with the relayed limit written once; the load moved above the
store and the store into the compare's delay slot. The scheduler reading is from sched.c and rtlanal.c; the judge decides
each child.
"""
import re

from .integer_repair_support import IDENT, INTEGER, edit, view
from .line_scan import lines

FAMILY = 'deref_member_store'
FAMILIES = (FAMILY,)
LIMIT = 8
NEAR = 6  # lines between the store and the global's read
WIDTH = re.compile(r'(?:[su](?:8|16|32)|char|short|int|unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int))')
EXTERN_POINTER = re.compile(rf'(?m)^[ \t]*extern\s+(?P<type>{WIDTH.pattern})\s*\*\s*(?P<name>{IDENT})\s*;[ \t]*$')
EXTERN_SCALAR = re.compile(rf'(?m)^[ \t]*extern\s+(?P<type>{INTEGER})\s+(?P<name>{IDENT})\s*;[ \t]*$')
LOCAL_POINTER = re.compile(rf'(?<![\w*])(?P<type>{WIDTH.pattern})\s*\*\s*(?P<name>{IDENT})\s*;')


def _norm(type_):
    return re.sub(r'\s+', ' ', type_)


def _record(type_):
    return '__repair_deref_' + _norm(type_).replace(' ', '_')


def _definition_start(clean, opening):
    return max(clean.rfind(ch, 0, opening) for ch in ';}') + 1


def _build(source, start, stores):
    """`source` with the chosen `(offset, end, pointer, type)` stores as members, or None."""
    edits, kinds = [], set()
    for at, end, pointer, type_ in stores:
        edits.append((at, end, f'((({_record(type_)} *) {pointer})->value)'))
        kinds.add(_norm(type_))
    typedefs = ''.join(f'\ntypedef struct {{ {t} value; }} {_record(t)};' for t in sorted(kinds)
                       if f'}} {_record(t)};' not in source[:start])
    return edit(source[:start] + typedefs + source[start:], [(s + len(typedefs), e + len(typedefs), r) for s, e, r in edits])


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body) or '__repair_deref_' in part.clean:
        return []
    start = _definition_start(part.clean, part.opening)
    head = part.clean[:start]
    pointers = {m['name']: _norm(m['type']) for m in EXTERN_POINTER.finditer(head)}
    scalars = {m['name'] for m in EXTERN_SCALAR.finditer(head)}
    for local in LOCAL_POINTER.finditer(part.clean, part.opening, part.end):
        if len(re.findall(rf'(?<![\w.>]){re.escape(local["name"])}\b\s*[;=,\[]', part.body)) >= 1:
            pointers[local['name']] = _norm(local['type'])
    if not pointers or not scalars:
        return []
    body = lines(part, source)
    found = []
    for index, line in enumerate(body):
        for hit in re.finditer(rf'(?:(?<=[;{{}})])|^)\s*(?P<lhs>\*\s*(?P<name>{IDENT}))\s*=(?!=)', line.text):
            pointer = hit['name']
            if pointer not in pointers or WIDTH.fullmatch(pointer):
                continue
            window = body[index + 1:index + 1 + NEAR]
            between = [w for w in window]
            if not any(re.search(rf'(?<![\w.>])(?:{"|".join(map(re.escape, sorted(scalars)))})\b(?!\s*\()', w.text) for w in between):
                continue
            reads = next(k for k, w in enumerate(window)
                         if re.search(rf'(?<![\w.>])(?:{"|".join(map(re.escape, sorted(scalars)))})\b(?!\s*\()', w.text))
            if any(re.search(r'\bgoto\b|\breturn\b|\bbreak\b|[{}]', w.text) for w in window[:reads]):
                continue
            found.append((line.start + hit.start('lhs'), line.start + hit.end('lhs'), pointer, pointers[pointer]))
    if not found:
        return []
    results = []
    children = ([found] if len(found) > 1 else []) + [[one] for one in found]
    for chosen in children:
        text = _build(source, start, chosen)
        if text and text != source and (FAMILY, text) not in results:
            results.append((FAMILY, text))
        if len(results) >= LIMIT:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}  # the registry: no caller wiring (registry.py)

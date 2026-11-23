"""A leading load staged in one shared local at every statement that computes from it, as one child.

`x = (*(u16 *)((char *)p + 0x40)) * 6;` read in each arm of a record builder compiles in the order the load comes in the
statement; the game's scheduler and allocator saw the length in a variable of its own and the product after it. Written
`len = (*(u16 *)((char *)p + 0x40)); x = len * 6;` with one `len` for every arm the order of the arms' loads and the
registers of everything after them changed: five arms of an 874-instruction KMC N64 object spawner (`-G0 -mips3 -mgp32
-mfp32 -O2`) 2756 -> 2386. Each arm alone scored 2756 (the same as the source): the staged name is one pseudo of the whole
function (references of every arm, a long live range), where a name per arm is five block-local pseudos, and
local-alloc.c and global.c order and colour those differently. The reading is from that difference in the allocation table,
not the compiler's source; the judge decides, and no child is a verdict.

`variants` takes every statement `V = (*(T *)((char *)P + K)) OP rest;` (a plain local on the left, an integer load of at most
four bytes as the leftmost operand, `OP` one of `*`, `<<`, `>>`, `+`, `-`, `|`, `&`) and, for each load type, offers one
child that writes all of that type's statements through one new `s32` local declared at the top of the function. At
least two statements are needed: a single one is already the plain form."""
import re

from .frame_slot_alias_split import _SIZES
from .integer_repair_support import IDENT, edit, view

FAMILY = 'shared_operand_stage'
FAMILIES = (FAMILY,)
_STATEMENT = re.compile(
    rf'(?<=[;{{}}])(?P<lead>[ \t]*\n?[ \t]*)(?P<lhs>{IDENT})\s*=\s*(?P<load>\(\*\(\((?P<type>(?:unsigned\s+)?{IDENT})\s*\*\)\s*'
    rf'\(\(\(char\s*\*\)\s*(?P<ptr>{IDENT})\)\s*\+\s*(?P<offset>0x[0-9A-Fa-f]+|\d+)\)\)\))\s*'
    rf'(?P<op>\*|<<|>>|\+|-|\||&)\s*(?P<rest>[^;{{}}]+?)\s*;')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    groups = {}
    for hit in _STATEMENT.finditer(clean, part.opening + 1, part.end):
        kind = ' '.join(hit['type'].split())
        if kind not in _SIZES or _SIZES[kind] > 4 or hit['lhs'] == hit['ptr']:
            continue
        groups.setdefault(kind, []).append(hit)
    result = []
    for kind, hits in sorted(groups.items()):
        if len(hits) < 2:
            continue
        stage = f'__repair_stage_{kind.replace(" ", "_")}'
        if re.search(rf'\b{stage}\b', source):
            continue
        changes = [(part.opening + 1, part.opening + 1, f'\n  s32 {stage};')]
        for hit in hits:
            indent = re.search(r'[ \t]*$', hit['lead'])[0]
            text = f'{hit["lead"]}{stage} = {hit["load"]};\n{indent}{hit["lhs"]} = {stage} {hit["op"]} {hit["rest"]};'
            changes.append((hit.start(), hit.end(), text))
        result.append((FAMILY, edit(source, changes)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)

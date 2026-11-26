"""A value-returning function with no `return`: return what the target's last loop branch leaves in `$v0`.

reorg fills a loop's closing branch with a copy of the first instruction at the loop's top. When that instruction writes
`$v0` and the function returns a value, `$v0` is live where the loop falls through to the exit, so the branch must be
annulled (`bnel`). A target with the plain `bnez` therefore either returns nothing, or computes the returned value again
after the loop (the copy in the slot is then harmless). Where the shared header already declares the function with a
result, the candidate cannot say `void`: a `return` of the value the slot computes gives the plain branch.

On a 149-instruction N64 distance check (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`) the slot was
`addu $v0, $s2, $s1`, a pointer parameter plus the loop counter; `return (s32) ((u8 *) arg1 + i);` took the score
from 205 to 5. The return is scaffolding: the game's function returned nothing.

Offered only when the target has a backward plain conditional branch whose slot writes `$v0` and whose fall-through
reaches `jr $ra` without touching `$v0`, and the source's function has a result type and no `return` with a value."""
import re

from .csource import find
from .integer_repair_support import edit, view
from .nonvoid_no_return import BRANCHES, _items, _writes_v0
from .run_weight_scope import _declared

FAMILY = 'slot_value_return'
FAMILIES = (FAMILY,)
LIMIT = 24


def slot_writes(asm):
    """The (op, args) of the slot of the target's loop branch that writes `$v0` and falls through to the exit, or None."""
    items = _items(asm)
    seen = set()
    for i, (op, args) in enumerate(items):
        if op == 'label':
            seen.add(args)
            continue
        if op not in BRANCHES or i + 1 >= len(items) or args.split(',')[-1].strip() not in seen:
            continue
        slot = items[i + 1]
        if slot[0] == 'label' or not _writes_v0(*slot):
            continue
        for after, rest in items[i + 2:]:
            if after == 'jr' and rest == '$ra':
                return slot
            if after == 'label':
                continue
            if after in BRANCHES or after in ('j', 'jal', 'jalr', 'b') or re.search(r'\$v0\b', rest):
                break
    return None


def variants(source, name, asm, header=''):
    slot = slot_writes(asm)
    if not slot:
        return []
    part = view(source, name)
    if not part:
        return []
    top = source.rfind('\n', 0, find(source, name)[0]) + 1
    head = re.search(rf'(?P<result>[^;{{}}]*?)\b{re.escape(name)}\s*\([^()]*\)\s*$', part.clean[top:part.opening].rstrip())
    body = part.clean[part.opening:part.end]
    if not head or re.search(r'\bvoid\s*$', head['result']) or re.search(r'\breturn\b\s*[^;\s]', body):
        return []
    kind = head['result'].split()
    kind = ' '.join(w for w in kind if w not in ('static', 'inline', 'extern'))
    names = _declared(part)
    counters = [n for n in sorted(names)
                if re.search(rf'(?<![\w.>]){n}\s*(?:\+\+|\+=)|\+\+\s*{n}\b', body)]
    text = part.clean[:part.end]
    pointers = [n for n in sorted(names - set(counters))
                if re.search(rf'(?:\*\s*|\bvoid\s*\*\s*){n}\s*[,);=\[]', text)]
    values = []
    if slot[0] == 'addu':
        values += [f'({kind}) ((u8 *) {p} + {i})' for i in counters for p in pointers]
    values += [f'({kind}) {i}' for i in counters]
    closing = source.rfind('}', part.opening, part.end + 1)
    return [(FAMILY, edit(source, [(closing, closing, f'    return {value};\n')])) for value in values[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'),
          'order': 65, 'archs': ('mips',)}

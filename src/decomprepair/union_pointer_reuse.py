"""A union's pointer member that only a later phase uses, written as the function's earlier pointer.

A search shares one union between a late pointer phase and an integer phase (`__repair_phase_storage.pointer = get();`
after a loop that tested and filled in `p = get();`, and `.value` as another arm's counter). The game used its one
pointer local again. Splitting the union (`phase_storage_split`) alone left the score as it was (120 -> 120 on a
96-instruction N64 sound setup routine, SN GCC `-O2`), so a greedy search never took the split that
`pointer_local_reuse` needs; the pair scored 60, and opening the remaining one-shot fences matched.

One child per merge: the union becomes one local per member, and one pointer member is written into another pointer
local of the same type whose life it never overlaps (`pointer_local_reuse`'s own flow check). Merges that retire none
of the union's members are left to `pointer_local_reuse`. The judge decides.
"""
import re

from . import phase_storage_split_repairs, pointer_pair_repairs
from .integer_repair_support import IDENT

FAMILY = 'union_pointer_reuse'
FAMILIES = (FAMILY,)


def variants(source, name, header=''):
    split = phase_storage_split_repairs.split(source, name)
    if not split:
        return []
    made = set(re.findall(IDENT, split)) - set(re.findall(IDENT, source))
    return [(FAMILY, text) for _, text in pointer_pair_repairs.reuse(split, name, header)
            if any(not re.search(rf'\b{member}\b', text) for member in made)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'),
          'order': 120}  # the registry: no caller wiring (registry.py)

"""A `volatile` cast written plain: the access the game made without the qualifier.

An agent (or `volatile_access_pin`) writes `*((volatile s32 *) (p + 0x5C)) |= K;` to keep two accesses through one base
from swapping, and a saved best keeps it long after the swap stopped mattering. A `volatile` access is more than an
ordering pin to the compiler: the load cannot move into a branch's delay slot (reorg.c will not fill it from a path that
may not run), `cse` never reuses it, and the first scheduler leaves it where it stands, so the statement beside it
(a `lui` that the target runs in the delay slot of the branch above) is the one that moves. In a KMC GCC 2.7.2 N64 object
spawner (`-G0 -mips3 -mgp32 -mfp32 -O2`, 713 instructions) the two flag-word updates of an `if`/`else`
(`|= 0x5E600` and `|= 0x20600`) were `volatile`: the branch had a `nop` where the target has the `lui`, the arms' first
two instructions were exchanged, and every jump-table entry after them was one word off (that scored 150 for the
switch's table alone). Written plain the function lost those rows (1990 -> 1830 in the chain), and the other families
could not offer it: nothing in the library removed a qualifier.

`variants` offers every `(volatile T *)` cast of the function written `(T *)`, all at once, then each one alone (at
most 6 proposals). Whether the qualifier belonged to the source is unknown; the judge decides, and a `volatile`
the game's own header declared (a memory-mapped register) is a variable's, not a cast's, and is left alone."""
import re

from .integer_repair_support import edit, view

FAMILY = 'volatile_cast_unpin'
FAMILIES = (FAMILY,)
LIMIT = 6
_CAST = re.compile(r'\(\s*volatile\s+((?:unsigned\s+|signed\s+)?[A-Za-z_]\w*(?:\s*\*)+)\s*\)')


def variants(source, name):
    """Proposals: all the function's volatile casts written plain, then each alone."""
    part = view(source, name)
    if not part:
        return []
    hits = list(_CAST.finditer(part.clean, part.opening + 1, part.end))
    if not hits:
        return []
    rewrite = lambda hit: (hit.start(), hit.end(), '(' + hit[1] + ')')
    out = [edit(source, [rewrite(hit) for hit in hits])]
    if len(hits) > 1:
        out += [edit(source, [rewrite(hit)]) for hit in hits]
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 120}  # the registry: no caller wiring (registry.py)

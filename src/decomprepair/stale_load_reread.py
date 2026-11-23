"""A load m2c kept in a local, read again where a store and a call come between it and the use.

m2c names the first read of a field (`id = *(u16 *)((char *)p + 0)`) and every later use takes the name; the game read the
field again where it needed it, after the stores and the call that stand between. gcc 2.7.2's cse folds a repeated
expression (`table + id * 0x4C`, the address the shifts and the add make) into the earlier one only while nothing writes
memory in between (`cse.c: note_mem_written`: any store invalidates the variable addresses), so a use written as the
load again recomputes it where a use of the local reuses the register that held it, and the register pressure of
everything between moves with it. In an 874-instruction KMC N64 object spawner (`-G0 -mips3 -mgp32 -mfp32 -O2`) the one use
of such a local inside a call's arguments, written as the load again (the 4C-byte record's address recomputed from `lhu`
with its shift chain, as the target has it), took 2386 -> 1971; no family offered it (the best of 2860 children was 2381).
Each reading is a hypothesis from the dumps and the target's own reload; the judge decides.

`variants` takes a local assigned once by `t = (*(T *)((char *)p + K));` (T an integer type of at most four bytes, `p` a
plain variable that is not written afterwards) and each later use of `t` that has a store (an assignment) or a call
between the load and it, and offers one child that writes that one use as the load, and one that does it for every such use.
At most twelve uses are offered one by one. Writing the load again assumes the intervening store does not change it,
which is the hypothesis the judge tests, so the family says it, and no child is a verdict."""
import re

from .frame_slot_alias_split import _SIZES
from .integer_repair_support import IDENT, edit, view

FAMILY = 'stale_load_reread'
FAMILIES = (FAMILY,)
LIMIT = 12
_LOAD = re.compile(rf'(?<=[;{{}}])\s*(?P<var>{IDENT})\s*=\s*\(?(?P<load>\*\(\((?P<type>(?:unsigned\s+)?{IDENT})\s*\*\)\s*'
                   rf'\(\(\(char\s*\*\)\s*(?P<ptr>{IDENT})\)\s*\+\s*(?P<offset>0x[0-9A-Fa-f]+|\d+)\)\))\)?\s*;')
_STORE = re.compile(r'(?<![=!<>])(?:[-+*/%&|^]|<<|>>)?=(?!=)')
_CALL = re.compile(rf'(?<![\w.>])(?!(?:if|while|for|switch|return|sizeof)\b)({IDENT})\s*\(')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body_start = part.opening + 1
    found = []
    for hit in _LOAD.finditer(clean, body_start, part.end):
        var, kind, pointer = hit['var'], ' '.join(hit['type'].split()), hit['ptr']
        if kind not in _SIZES or _SIZES[kind] > 4 or var == pointer:
            continue
        everything = clean[body_start:part.end]
        if len(re.findall(rf'(?<![\w.>]){re.escape(var)}\s*=(?!=)', everything)) != 1:
            continue
        after = hit.end()
        uses = []
        for use in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b(?!\s*=(?!=))', clean[after:part.end]):
            start = after + use.start()
            between = clean[after:max(clean.rfind(c, after, start) for c in ';{}') + 1]
            if re.search(rf'(?<![\w.>]){re.escape(pointer)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', between):
                break
            if (_STORE.search(between) or _CALL.search(between)):
                uses.append((start, after + use.end()))
        if uses:
            found.append((f"({hit['load']})", uses))
    result = []
    for load, uses in found:
        for start, end in uses[:LIMIT]:
            result.append((FAMILY, edit(source, [(start, end, load)])))
        if len(uses) > 1:
            result.append((FAMILY, edit(source, [(start, end, load) for start, end in uses])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)

"""rmw_read_fence: a global's increment after a may-alias store, its read moved before the store behind a loop note.

KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) target shape: `... and; sll; or; lhu counter; sw value,0x10(p); lbu flag;
addiu counter,1; sh counter`: the counter is loaded after the packed value's `or` and before the store, in the register
the shift's result has just freed. Written `*(volatile T *)&p->f = v; G++;` the load stays behind the store (a cast store
is a non-struct memory reference that may alias the global, so sched.c keeps the later read after it: 60 on one
function). Read into a local of its own before the store, the first scheduler hoists the load above the shift (a load
with no predecessor has priority 1, and the memory unit blocks it in the slot before the store: 425), so it overlaps the
shift's register. Wrapped in `do { c = G; } while (0);` the read follows a loop note, and sched.c makes the insn after a
loop note depend on every insn before it (`sched_analyze`, the `NOTE_INSN_LOOP_BEG/END` case), so the load stays after
the `or`; `c` keeps one set and one death, a block-local pseudo that local-alloc gives the freed register (60 -> 0 on a
118-instruction menu update; the shared-local form of `volatile_rmw_counter_share` reached only 25, its local having two
deaths and going to global.c). The loop-note rule is read from sched.c; the register outcome is measured on one function.

The shape: a statement storing through a dereference (`*expr = value;`, a `volatile` cast included) immediately followed by
`G++;`, `G += K;` or `G = G + K;` for a global `G` whose `extern` declaration (in the source or the header) names its type.
The child writes
    do { c = G; } while (0);
    *expr = value;
    G = c + K;
"""
import re

from .call_carrier_pointer_split import IDENT, UNORDERED
from .integer_repair_support import edit, view

FAMILY = 'rmw_read_fence'
FAMILIES = (FAMILY,)

NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
PAIR = re.compile(
    rf'(?P<lead>[ \t]*)(?P<store>\*[^;{{}}]*?[^=!<>+\-*/%&|^]=(?!=)[^;{{}}]*;)[ \t]*\n'
    rf'[ \t]*(?P<glob>{IDENT})\s*(?:\+\+|\+=\s*(?P<k>{NUMBER})|=\s*(?P=glob)\s*\+\s*(?P<k2>{NUMBER}))\s*;[ \t]*\n')


def _fresh(clean, base):
    name = base
    while re.search(rf'\b{name}\b', clean):
        name += '_'
    return name


def _global_type(texts, glob):
    """The type of `extern TYPE glob;`, or None when it is not a plain scalar (pointer, array, volatile, unknown)."""
    for text in texts:
        hit = re.search(rf'^\s*extern\s+(?P<type>[\w ]+?)\s+{glob}\s*;', text or '', re.M)
        if hit:
            kind = hit['type'].strip()
            return None if 'volatile' in kind.split() else kind
    return None


def variants(source, name, header=''):
    part = view(source, name)
    if not part or UNORDERED.search(part.body):
        return []
    clean = part.clean
    out = []
    for hit in PAIR.finditer(clean, part.opening, part.end):
        glob = hit['glob']
        if re.search(rf'\b{glob}\b', hit['store']) or re.search(rf'\b{glob}\s*\(', clean):
            continue
        kind = _global_type((source, header), glob)
        if kind is None:
            continue
        c = _fresh(clean, 'rmw_c')
        lead, step = hit['lead'], hit['k'] or hit['k2'] or '1'
        text = (f'{lead}do {{\n{lead}  {c} = {glob};\n{lead}}} while (0);\n'
                f'{lead}{source[hit.start("store"):hit.end("store")]}\n'
                f'{lead}{glob} = {c} + {step};\n')
        opening = part.opening + 1
        out.append((FAMILY, edit(source, [(hit.start(), hit.end(), text), (opening, opening, f'\n  {kind} {c};')])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 50}  # the registry: no caller wiring (registry.py)

"""volatile_rmw_counter_share: a counter read before a volatile read-modify-write store, in the masked value's local.

KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) target shape: `lw color; lhu alpha; and; sll; or; lhu counter; sw color;
lbu flag; addiu counter,1; sh counter`: the counter's load sits between the packed value's `or` and the store. Written
`*(volatile u32 *)&p->f = (p->f & M) | REST; G++;` the store comes first (the cast store is a non-struct memory reference,
so sched.c keeps the later load behind it); a counter local of its own is read at priority 1 (load cost 3, no
predecessor) and the first scheduler hoists it above the shift (460). Naming the masked part and reading the counter into
THE SAME local after the `or` has consumed it gives the load a write-after-read edge from the `or`, so it is
scheduled right before the store (60 -> 30 on one function; the shared local has two deaths and is a global pseudo, so five
register rows remain, which `scalar_storage_reuse` trims to 25). Hypothesis from sched.c `priority`/`rank_for_schedule`,
measured on one function; the exact judge decides.

The shape: `*((volatile T *)(&P->F)) = (P->F & MASK) | REST;` immediately followed by `G++;` (or `G += 1;`), inside
a block. The child declares three locals and writes
    m = P->F & MASK; t = REST; cur = m | t; m = G; *(volatile T *)(&P->F) = cur; G = m + 1;
"""
import re

from .call_carrier_pointer_split import IDENT, UNORDERED
from .integer_repair_support import edit, view

FAMILY = 'volatile_rmw_counter_share'
FAMILIES = (FAMILY,)

STORE = re.compile(
    rf'(?P<lead>[ \t]*)\*\s*\(\s*\(\s*volatile\s+(?P<type>[\w ]+?)\s*\*\s*\)\s*\(\s*&\s*(?P<ptr>{IDENT})\s*->\s*(?P<field>{IDENT})\s*\)\s*\)'
    rf'\s*=\s*\(\s*(?P=ptr)\s*->\s*(?P=field)\s*&\s*\((?P<mask>[^;()]+)\)\s*\)\s*\|\s*\((?P<rest>[^;]+)\)\s*;[ \t]*\n'
    rf'[ \t]*(?P<glob>{IDENT})\s*(?:\+\+|\+=\s*1)\s*;[ \t]*\n')


def _fresh(clean, base):
    name = base
    while re.search(rf'\b{name}\b', clean):
        name += '_'
    return name


def variants(source, name):
    part = view(source, name)
    if not part or UNORDERED.search(part.body):
        return []
    clean = part.clean
    hit = STORE.search(clean, part.opening, part.end)
    if not hit:
        return []
    m, t, cur = (_fresh(clean, base) for base in ('rmw_m', 'rmw_t', 'rmw_cur'))
    lead, kind, ptr, field = hit['lead'], hit['type'].strip(), hit['ptr'], hit['field']
    target = f'*((volatile {kind} *) (&{ptr}->{field}))'
    text = (f'{lead}{m} = {ptr}->{field} & ({hit["mask"]});\n'
            f'{lead}{t} = {hit["rest"]};\n'
            f'{lead}{cur} = {m} | {t};\n'
            f'{lead}{m} = {hit["glob"]};\n'
            f'{lead}{target} = {cur};\n'
            f'{lead}{hit["glob"]} = {m} + 1;\n')
    opening = part.opening + 1
    declare = f'\n  u32 {m};\n  u32 {t};\n  u32 {cur};'
    return [(FAMILY, edit(source, [(hit.start(), hit.end(), text), (opening, opening, declare)]))]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 50}  # the registry: no caller wiring (registry.py)

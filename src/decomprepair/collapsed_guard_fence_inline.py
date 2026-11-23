"""An identical-arm guard collapsed, a one-shot `do { } while (0)` fence dropped and a store-adjacent local read inline, as one child.

m2c leaves three scaffolds standing in a colour-update function whose arms each store a value into three bytes of
one record: `if (temp) { S } else { S }` on a local nothing assigned (the condition reads an uninitialised byte), a
`do { ... } while (0);` that fenced the first arm's stores, and a function-level scratch local (`var_v0`) that one arm
sets to a literal and another arm sets to a global's byte just before the store that reads it. On a KMC
(`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) 130-instruction function the saved best scored 870; the guard
collapsed alone scored 2585 (the two random-colour arms then cross-jump into one), the local read inline alone 1170
and the fence dropped alone 870 (no change), and all three together scored 0: with the arms' registers decided by
their own pseudos, the first arm's tail jumps into the second arm's byte store. Neither half is a step the chain would
keep, so one child carries all three edits (a hypothesis about the register and cross-jump effect; the measured
result is the evidence, and the exact judge decides).

The collapse (`identical_arm_collapse`), the scope unwrap (`one_shot_scope`) and the adjacent inline
(`single_use_inline`: the assignment may now share its line with the statement before it) are the library's own
families; this one applies them in turn to the text the previous step made, and offers a child only when all three
applied. Each is also offered alone by its own family, so nothing is lost when the combination is wrong.
"""
from . import compiler_shape_repairs, identical_arm_collapse_repairs, local_inline_repairs
from .integer_repair_support import view

FAMILY = 'collapsed_guard_fence_inline'
FAMILIES = (FAMILY,)
COLLAPSES = 3
UNWRAPS = 2
INLINES = 4


def variants(source, name, header=''):
    out = []
    for _, collapsed in identical_arm_collapse_repairs.variants(source, name, header)[:COLLAPSES]:
        if collapsed == source:
            continue
        unwrapped = [text for family, text in compiler_shape_repairs.variants(collapsed, name, 'mips', (), header)
                     if family == 'one_shot_scope' and text != collapsed][:UNWRAPS]
        for fenced in unwrapped:
            part = view(fenced, name)
            if not part:
                continue
            out.extend((FAMILY, text) for text in
                       [t for _, t in local_inline_repairs._adjacent(fenced, part)][:INLINES] if text != fenced)
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 60}  # the registry: no caller wiring (registry.py)

"""An identical-arm guard collapsed and two integer locals merged, as one child.

m2c leaves `if (temp) { S } else { S }` standing where the game had one value, often on a local nothing assigned (the
condition reads an uninitialised word). The compiler folds the equal arms but the dead read keeps the local's pseudo
alive from the function's entry, and also keeps a `& 0xFF` test alive that the folded value would drop. On a KMC
(`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) 74-instruction audio function whose saved best scored 60, collapsing the
guard alone scored 110, merging the halfword local into the flag's integer local alone (`merge_integer_lifetimes`)
scored 690, and both together scored 0: the flag got `$v0`, as in the target, once its long range was gone and the
loaded halfword shared its pseudo. Neither half is a step the chain would keep, so one child carries both edits
(a hypothesis about the register effect; the measured result is the evidence, and the exact judge decides).

The first merge each collapsed copy admits is combined with it; the collapse and the merge are also offered one after
the other by their own families, so nothing is lost when the pair is wrong."""
from . import identical_arm_collapse_repairs, integer_lifetime_repairs

FAMILY = 'collapsed_guard_lifetime_merge'
FAMILIES = (FAMILY,)
COLLAPSES = 4
MERGES = 3


def variants(source, name, header=''):
    out = []
    for _, collapsed in identical_arm_collapse_repairs.variants(source, name, header)[:COLLAPSES]:
        merges = [text for family, text in integer_lifetime_repairs.variants(collapsed, name, header)
                  if family == 'merge_integer_lifetimes' and text != collapsed]
        out.extend((FAMILY, text) for text in merges[:MERGES] if text != source)
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)

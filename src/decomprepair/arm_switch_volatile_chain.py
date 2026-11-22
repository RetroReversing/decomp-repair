"""Identical-arm store collapse, the grouped-label range switch and a volatile scalar reload, as one child.

A KMC gcc 2.7.2 save-menu function sat at 30 (the chosen action in `$a0` instead of `$v0`) and only the three steps
together made it exact: the duplicated store (`if (x) { G = v; } else { G = v; }`) written once at the join
(identical_arm_collapse), m2c's range-test tree written as the grouped-label `switch` (range_assignment_switch) and
the stored-then-read flag declared `volatile` (scalar_reload_volatile). Each step alone, or the greedy order, scores
worse (340, 550, 70, then 220 with the split-body switch), so a search that keeps only improvements never reaches
the match. This offers the combination: every collapse child, its first (grouped) switch, and each volatile child of
that. Hypothesis, not confirmed in the compiler source: the volatile reload frees the value from the call argument
it was forwarded into, so it keeps `$v0`.
"""
from . import identical_arm_collapse_repairs, range_assignment_switch_repairs, scalar_reload_volatile_repairs

FAMILY = 'arm_switch_volatile_chain'
FAMILIES = (FAMILY,)


def variants(source, name):
    result = []
    for _, collapsed in identical_arm_collapse_repairs.variants(source, name):
        for _, switched in range_assignment_switch_repairs.variants(collapsed, name)[:1]:
            for _, volatile in scalar_reload_volatile_repairs.variants(switched, name):
                if volatile not in [text for _, text in result]:
                    result.append((FAMILY, volatile))
    return result[:4]

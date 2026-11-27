"""one_web_split: ONE assignment web of a shared local given a name of its own, the other webs keeping the name.

`local_web_split` gives every web its own local. The target can give one arm's value a register of its own while the
other arms still share one: a 249-instruction N64 function whose four player arms each set a result flag had `$a1` in
one arm and `$a0` in three (`sn-n64-281 -G0 -mips3 -O2`, 2545 -> 1300), and two of the three had to keep one name for
one arm to jump into the other's test of it (`chain_arm_check_goto`, then 90), which the split of every web rules out.

Webs and the conditions that leave one alone are `local_web_split`'s. Children: each web alone, the last first, for
every local with three or more (with two, one web alone is the whole split).
"""
from .case_temporary_repairs import _identifiers
from .local_web_split import _apply, plans_of

FAMILY = 'one_web_split'
FAMILIES = (FAMILY,)
LIMIT = 16
PER_LOCAL = 8


def variants(source, name):
    """[(family, source)]: one web of one local renamed."""
    clean, plans = plans_of(source, name)
    found = []
    for decl, var, webs in plans:
        if len(webs) < 3:
            continue
        for k in [k for k, web in enumerate(webs) if web[2]][::-1][:PER_LOCAL]:
            alone = [(members, spans, i == k, first) for i, (members, spans, _, first) in enumerate(webs)]
            child = _apply(source, clean, [(decl, var, alone)], False, _identifiers(source))
            if child != source:
                found.append((FAMILY, child))
    return found[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

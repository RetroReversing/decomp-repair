"""A call's result local reused to hold the value computed from it, instead of a new local for that value.

m2c names every value it computes after its own register, so a call result and what is made of it get two locals:

    temp_v0 = f(x);
    if (temp_v0 == 0) { var_a0 = 0x64; } else { var_a0 = (temp_a1 * 0x4650) / temp_v0; }
    if (temp_a1 < var_a0) { var_a0 = temp_a1; }
    sum += var_a0;

The game's source kept one variable, `temp_v0 = (temp_a1 * 0x4650) / temp_v0;`, and KMC GCC 2.7.2 (`-O1`) then gave the
two-armed result the register the call result was in (`$a0` where the draft's second local took `$v1`): a 127-instruction
N64 function at 25 -> 0, the five differing rows all registers.

A site is `if (C) { V = X; } else { V = Y; }` (each arm one assignment) whose condition `C` reads a local `R` of the same
declared type that is assigned a value earlier, with `V` not mentioned before the `if` and `R` read nowhere after the
`else` except as the target of a later assignment (the next iteration's call). Every `V` from the `if` on becomes `R`.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'result_local_reuse'
FAMILIES = (FAMILY,)
_SITE = re.compile(rf'\bif\s*\(([^{{}};]*)\)\s*{{\s*({IDENT})\s*=\s*([^;{{}}]+);\s*}}\s*else\s*{{\s*\2\s*=\s*([^;{{}}]+);\s*}}')
LIMIT = 4


def _type(clean, local):
    hit = re.search(rf'\b((?:unsigned\s+)?\w+)\s+{local}\s*;', clean)
    return hit and hit[1]


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for site in _SITE.finditer(part.clean, part.opening, part.end):
        condition, value = site[1], site[2]
        for result in dict.fromkeys(re.findall(IDENT, condition)):
            if result == value or not _type(part.clean, result) or _type(part.clean, result) != _type(part.clean, value):
                continue
            before = part.clean[part.opening:site.start()]
            if re.search(rf'\b{value}\b', before.replace(f' {value};', '')) or not re.search(rf'\b{result}\s*=[^=]', before):
                continue
            after = part.clean[site.end():part.end]
            if any(not re.match(r'\s*=[^=]', after[m.end():]) for m in re.finditer(rf'\b{result}\b', after)):
                continue
            tail = part.clean[site.start():part.end]
            edits = [(site.start() + m.start(), site.start() + m.end(), result)
                     for m in re.finditer(rf'\b{value}\b', tail)]
            out.append((FAMILY, edit(source, edits)))
            break
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

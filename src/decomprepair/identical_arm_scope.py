"""identical_arm_scope: an `if (c) { S } else { S }` with equal arms written once, inside a one-shot `do { } while (0)`.

`identical_arm_collapse` writes the arm's statements in place of the `if`. The folded branch still weighted the arm's
references by one more loop level (flow.c counts a reference at the depth of the loop notes around it, and a branch
the compiler folds late still sat inside its own block), and a register choice can hang on that weight: on a
2,267-instruction KMC collision routine (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`) the clamp
`if (p) { t = y + a7; } else { t = y + a7; }` collapsed plainly cost the float argument `a7` its saved register
(7266 -> 8383), and written `do { t = y + a7; } while (0);` it kept it and moved two others to the target's registers
(7266 -> 7009; hypothesis for the mechanism: one function's allocation, not read in the compiler source). The same
conditions as `identical_arm_collapse` (plain statements, a condition with no call or assignment)."""
import re

from .identical_arm_collapse_repairs import ARMS
from .integer_repair_support import edit, view

FAMILY = 'identical_arm_scope'
FAMILIES = (FAMILY,)
LIMIT = 8


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for m in ARMS.finditer(part.clean, part.opening, part.end):
        cond = m['cond']
        if re.search(r'[A-Za-z_]\w*\s*\(|(?<![=!<>])=(?!=)|\+\+|--', re.sub(r'\(\s*(?:u|s)(?:8|16|32)\s*\)\s*', '', cond)):
            continue
        a, b = (' '.join(m[k].split()) for k in ('a', 'b'))
        if not a or a != b:
            continue
        lines = [line.strip() for line in source[m.start('a'):m.end('a')].strip().split('\n') if line.strip()]
        text = edit(source, [(m.start(), m.end(), 'do { ' + ' '.join(lines) + ' } while (0);')])
        if text != source:
            out.append((FAMILY, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}  # the registry: no caller wiring (registry.py)

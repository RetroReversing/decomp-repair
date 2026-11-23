"""A flag temporary m2c assigns in several places, written as the mask test where it is read.

m2c keeps each `flags & K` it meets in a local (`var_v0_2 = flags & 4; ... if (var_v0_2 != 0)`), assigns the same value again
inside branches, and tests the temporary later. The original wrote `if (flags & 4)` where it tested. GCC 2.7.2 (KMC,
`-G0 -mips3 -mgp32 -mfp32 -O2`) numbers the pseudos by first mention, so each temporary was a pseudo of its own whose
set sits where m2c put it (an `andi` hoisted above a branch, a second one copied into a delay slot, a register held
across a call), and the temporaries' references raise the flag word's own priority and move the saved registers around it
(a 445-instruction N64 target picker: 3113 -> 2593 by this edit alone).

For a local assigned only as `v = x & K;` with one `x` and `K` everywhere, where `x` is assigned at most once in the function
(or is a parameter that is never assigned) and that assignment precedes every mention of `v`, each read of `v` becomes
`(x & K)` and the assignments go. A candidate for the exact judge, never a verdict.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'flag_temp_inline'
FAMILIES = (FAMILY,)
LIMIT = 8
_ASSIGN = re.compile(r'(?m)^[ \t]*([A-Za-z_]\w*)[ \t]*=[ \t]*([A-Za-z_]\w*)[ \t]*&[ \t]*(0[xX][0-9a-fA-F]+|\d+)[ \t]*;[ \t]*\n')


def _writes(clean, name):
    return re.findall(rf'(?<![\w.>]){re.escape(name)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|(?:\+\+|--)\s*{re.escape(name)}\b|(?<![\w.>]){re.escape(name)}\s*(?:\+\+|--)', clean)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    seen = {}
    for hit in _ASSIGN.finditer(clean, part.opening, part.end):
        seen.setdefault(hit[1], []).append(hit)
    by_var = []
    for var, hits in seen.items():
        if len({(h[2], h[3]) for h in hits}) != 1 or var == hits[0][2]:
            continue
        word, mask = hits[0][2], hits[0][3]
        if len(_writes(body, word)) > 1 or len(_writes(body, var)) != len(hits):
            continue
        assigned = {(h.start(), h.end()) for h in hits}
        first_write = re.search(rf'(?<![\w.>]){re.escape(word)}\s*=(?!=)', body)
        declaration = re.search(rf'(?m)^[ \t]*[A-Za-z_][\w \t*]*[ \t*]{re.escape(var)}[ \t]*;[ \t]*\n', body)
        reads = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(var)}\b', body)
                 if not any(a <= part.opening + m.start() < b for a, b in assigned)
                 and not (declaration and declaration.start() <= m.start() < declaration.end())]
        if not reads or any(part.opening + m.start() < min(a for a, _ in assigned) for m in reads):
            continue
        if first_write and any(m.start() < first_write.start() for m in reads):
            continue
        edits = [(h.start(), h.end(), '') for h in hits]
        edits += [(part.opening + m.start(), part.opening + m.end(), f'({word} & {mask})') for m in reads]
        if declaration:
            edits.append((part.opening + declaration.start(), part.opening + declaration.end(), ''))
        by_var.append(edits)
    result = [edit(source, edits) for edits in by_var[:LIMIT]]
    if len(by_var) > 1:
        result.append(edit(source, [item for edits in by_var for item in edits]))
    return [(FAMILY, text) for text in result if text != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 100}  # the registry: no caller wiring (registry.py)

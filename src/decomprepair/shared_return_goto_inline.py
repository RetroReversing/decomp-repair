"""m2c's `goto __shared_return_0;` written as the `return 0;` its label stands for.

m2c joins equal returns into one labelled statement inside an arm and jumps to it from the others:

    if (c) { __shared_return_0: return 0; }  ...  goto __shared_return_0;

A label on `return K;` (K a literal) can only be reached to return K, so each `goto` to it is `return K;` and the label
goes. The draft's guards then read as plain early exits, which the other guard repairs (and `shared_return`) work on:
a 7-argument N64 function with three such exits went from the draft's 411 to a family chain that reached 0.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'shared_return_goto_inline'
FAMILIES = (FAMILY,)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    text = part.clean
    edits = []
    for label in re.finditer(rf'\b({IDENT})\s*:\s*return\s+({NUMBER})\s*;', text[part.opening:part.end]):
        start = part.opening + label.start()
        gotos = list(re.finditer(rf'\bgoto\s+{label[1]}\s*;', text[part.opening:part.end]))
        if not gotos:
            continue
        edits.append((start, start + len(label[1]) + (label.group(0).index(':') - len(label[1])) + 1, ''))
        edits += [(part.opening + g.start(), part.opening + g.end(), f'return {label[2]};') for g in gotos]
    return [(FAMILY, edit(source, edits))] if edits else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

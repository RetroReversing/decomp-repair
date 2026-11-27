"""Every byte step m2c wrote on a typed pointer, rewritten together.

`pointer_byte_step` (pointer_scale_repairs) offers one site per child. A draft often writes the same mistake twice, and
a caller that takes one child (a draft cleanup stage) then leaves the other: an N64 function read one table slot as
`*((i * 4) + &D)` at two places, the draft pass fixed the first and stayed one instruction off (150: `sll` by 4 for 2)
until the second was written `(&D)[i]` too. This offers all the sites in one child, when there are at least two.
"""
from .pointer_scale_repairs import edits

FAMILY = 'pointer_byte_step_all'
FAMILIES = (FAMILY,)


def variants(source, name, asm=''):
    chosen = []
    for start, end, text in sorted(set(edits(source, name, asm))):
        if not chosen or start >= chosen[-1][1] and start != chosen[-1][0]:
            chosen.append((start, end, text))
    if len(chosen) < 2:
        return []
    for start, end, text in reversed(chosen):
        source = source[:start] + text + source[end:]
    return [(FAMILY, source)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 100}

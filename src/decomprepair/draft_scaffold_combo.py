"""The four draft-scaffolding repairs of one display-list loop, applied together as one child.

A saved draft that a long search touched carries several edits that each cost something alone and pay off together:
the hand-made `volatile struct` frame (`volatile_stack_struct_drop`), a float conversion hoisted into a local
(`conversion_local_inline`), a byte copy half used (`narrow_copy_reuse`) and a mask spliced into a conjunction
(`literal_mask_conjunction`). A greedy chain that takes them one at a time goes down another road: on a 313-instruction
display-list loop (KMC GCC 2.7.2, `-O2 -G0 -mips3`) the chain from the saved best (2760) took the frame (2750), then the
GBI macro rewrite (1750) while the conjunction was still there, and stopped at 1480 after taking the other three; the
same four applied first give 2245 and the library's chain goes on from there.

`variants` applies, in that order, the first child of the frame repair, the first child of the conversion repair (every
conversion local at once when there are several), the last child of the byte-copy repair (all its edits) and, for each of
the conjunction repair's children, that one: a child per conjunction child (at most 12). It needs at least two of the four
to apply, since one alone is the module's own child. A hypothesis about the order of the edits; the exact judge decides."""
from . import (
    conversion_local_inline,
    literal_mask_conjunction,
    narrow_copy_reuse,
    volatile_stack_struct_drop,
)

FAMILY = 'draft_scaffold_combo'
FAMILIES = (FAMILY,)
LIMIT = 12


def _children(module, source, name, header):
    try:
        found = module.variants(source, name, header) if module is conversion_local_inline else module.variants(source, name)
    except Exception:  # noqa: BLE001 - a rule that cannot read the draft proposes nothing
        return []
    return [text for item in found for text in ((item[1],) if isinstance(item, tuple) else (item,))]


def variants(source, name, header=''):
    texts = [source]
    applied = 0
    for module, pick in ((volatile_stack_struct_drop, 'first'), (conversion_local_inline, 'first'),
                         (narrow_copy_reuse, 'last'), (literal_mask_conjunction, 'all')):
        grown = []
        for text in texts:
            found = [child for child in _children(module, text, name, header) if child != text]
            if not found:
                grown.append(text)
                continue
            grown += [found[0]] if pick == 'first' else [found[-1]] if pick == 'last' else found
        if any(text != source for text in grown) and grown != texts:
            applied += 1
        texts = grown
    out = [(FAMILY, text) for text in dict.fromkeys(texts) if text != source]
    return out[:LIMIT] if applied >= 2 else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 120, 'directives': True}  # the registry: no caller wiring (registry.py)

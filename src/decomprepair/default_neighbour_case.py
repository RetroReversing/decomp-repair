"""A `switch` whose `default:` arm also answers the value just below its lowest case, written with that case label.

GCC 2.7.2 lowers a small `switch` to a tree of compares. For cases `2` and `3..4` with a plain `default:` the tree is
`beq 2`, `slti 2` (below the lowest case: default), `slti 5`; the target of a 534-instruction panel builder's second
switch was `beq 2`, `slti 3`, `slti 5`: the lowest case had a left neighbour in the tree, because the game's switch also
named the value just below it (`case 1:` sharing the default's arm, an arm m2c merges into `default:`). The tree with that
label has the `GT 2` test where the tree without it has the `LT 2` test (the root is the case with a subtree on each side);
970 -> 820 on that function with the one label. The reading of stmt.c's `emit_case_nodes` is a hypothesis; measured
on a compare snippet (`case 1: default:` gives `beq 2; slti 3; slti 5`) and on the function.

`variants` finds each `switch (V) {` that has `default:` and at least two numeric `case N:` labels whose lowest value `m` is
at least 1, `m - 1` not a label, and writes `case m-1:` right before `default:` (or after it when `default:` comes first
in the block, as the same label list). One child per switch, at most 3."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'default_neighbour_case'
FAMILIES = (FAMILY,)
LIMIT = 3
SWITCH = re.compile(r'\bswitch\s*\([^{};]*\)\s*\{')
CASE = re.compile(r'(?<![\w.])case\s+(0[xX][0-9a-fA-F]+|\d+)\s*:')
DEFAULT = re.compile(r'(?<![\w.])default\s*:')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    for hit in SWITCH.finditer(clean, span[0], span[1]):
        open_at = hit.end() - 1
        stop = close(clean, open_at, '{', '}')
        if not stop:
            continue
        block = clean[open_at + 1:stop - 1]
        values = [int(m[1], 0) for m in CASE.finditer(block)]
        default = DEFAULT.search(block)
        if len(values) < 2 or not default or re.search(r'\bswitch\b', block):
            continue  # (a nested switch's labels are not this one's)
        low = min(values)
        if low < 1 or low - 1 in values:
            continue
        at = open_at + 1 + default.start()
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, at) + 1:at])[0]
        if source[source.rfind('\n', 0, at) + 1:at].strip():
            continue
        label = f'case {low - 1}:\n{indent}'
        out.append(source[:at] + label + source[at:])
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 68}

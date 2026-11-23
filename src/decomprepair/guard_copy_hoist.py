"""A pure copy that opens an `if` arm, moved above the `if` so it is live across the guard.

`if (G) { V = E; ... }` with `E` a cast or copy of parameters and locals: written inside the arm, `V`'s life starts after
the branch. Moved above (`V = E; if (G) { ... }`) its life overlaps every value the guard reads, so global.c records a
conflict with them and `find_reg` (which takes the first free register of `reg_alloc_order`) has to pass over their
registers. Delay-slot filling (reorg.c) then puts the copy back in the branch's slot, so the instruction order does not
change: only the register does. A slot setter (KMC GCC 2.7.2, `-O2 -G0 -mips3`) stood at 15 with the post-loop
`id = (u8) action` in `$a1` where the target has `$a3`; the late `j = (u8) action` (sharing the loop counter's local,
in `$a1`) opened the `if (id < 31)` arm, and hoisted above it `j` was live across `id`'s last read, so `id` lost `$a1`
and took `$a3` (15 -> 0). The allocator reading is a hypothesis the measurement agrees with; the judge decides each
child.

The child (`guard_copy_hoist`, one per qualifying arm, bounded) moves `V = E;` from the start of the arm to just before
the `if`, when:
- `E` reads only parameters and locals (no call, memory read, address, increment or assignment);
- the guard neither reads nor assigns `V`, and assigns none of `E`'s names;
- the `if` has no `else`, and after the arm `V` is not read before its next plain assignment (the false path now also
  sets `V`, which nothing reads).
"""
import re

from .csource import _blank, find
from .reassigned_local_inline import IDENT, TYPES, _match

FAMILY = 'guard_copy_hoist'
FAMILIES = (FAMILY,)
LIMIT = 8


def variants(source, name):
    clean = _blank(source)
    span = find(source, name)
    if not span or re.search(r'\b(?:volatile|asm|__asm__)\b', clean[span[0]:span[1]]):
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    known = set(re.findall(rf'\b{IDENT}\b', clean[start:opening])) | set(
        re.findall(rf'\b(?:{"|".join(TYPES)})\s+\**\s*({IDENT})\s*[;=,\[]', clean[opening:end]))
    result = []
    for hit in re.finditer(r'(?<![\w.])if\s*\(', clean[opening:end]):
        at = opening + hit.start()
        close = _match(clean, opening + hit.end() - 1)
        if close < 0:
            continue
        arm = re.match(rf'\s*\{{\s*({IDENT})\s*=(?!=)\s*([^;{{}}=]+);', clean[close + 1:end])
        if not arm:
            continue
        var, value = arm[1], arm[2].strip()
        names = set(re.findall(IDENT, value)) - TYPES
        if var not in known or var in TYPES or var in names or not names <= known:
            continue
        if re.search(r'\w\s*\(|\[|->|&|\+\+|--|[^=!<>]=[^=]|(?<![\w)])\*', value):
            continue
        guard = clean[at:close + 1]
        if re.search(rf'(?<![\w.>]){var}\b', guard):
            continue
        if re.search(rf'(?<![\w.>])(?:{"|".join(re.escape(n) for n in names) or "$^"})\s*(?:[-+*/&|^]|<<|>>)?=(?!=)|\+\+|--', guard):
            continue
        brace = clean.find('{', close)
        arm_end = _match(clean, brace)
        if arm_end < 0 or re.match(r'\s*else\b', clean[arm_end + 1:end]):
            continue
        after = re.compile(rf'(?<![\w.>]){var}\b').search(clean, arm_end + 1, end)
        if after and not re.match(r'\s*=(?!=)', clean[after.end():]):
            continue
        copy_start, copy_end = close + 1 + arm.start(1), close + 1 + arm.end()
        statement = source[copy_start:copy_end]
        rest = re.match(r'[ \t]*\n?[ \t]*', source[copy_end:]).end()
        text = source[:at] + statement + ' ' + source[at:copy_start] + source[copy_end + rest:]
        if text != source and text not in result:
            result.append(text)
    return [(FAMILY, text) for text in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)

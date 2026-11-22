"""A local computed on one line and read only by the store on the next, written into that store.

m2c names every intermediate: `temp = (idx * 8) + *(u8 **)(base + 4);` and then one store whose value reads `temp`
three times (a halfword and two bytes at its address). gcc 2.7.2 expands a store's address before its value, so with the
named temp the sum is built first, ahead of the destination's own address arithmetic; written into the store the
destination's `(counter * 4) + base` comes first and the sum after it, which is the order of the target's instructions
(KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`: a 219-instruction N64 sequencer function, 220 -> 160, the rest of the
rows then registers). The same expression read three times is one value after cse. A hypothesis, read from the
instruction order, not from the compiler's source.

The shape: a plain scalar or pointer local `T` with one assignment `T = expr;` (no call, no `++`/`--`, no assignment in
`expr`), immediately followed by one statement that stores through a dereference whose own text does not mention `T`
and whose value reads `T` two or more times, and no other mention of `T` anywhere. The reads become
`((type)(expr))`, the declaration goes.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'store_temp_inline'
FAMILIES = (FAMILY,)
LIMIT = 6

ASSIGN = re.compile(r'(?m)^([ \t]*)([A-Za-z_]\w*)\s*=(?!=)\s*([^;{}]+);[ \t]*\n(?=[ \t]*([^;{}]+);)')


def _top_level_equals(text):
    depth = 0
    for index, char in enumerate(text):
        depth += (char in '([')-(char in ')]')
        if char == '=' and depth == 0 and text[index - 1:index] not in ('=', '!', '<', '>') and text[index + 1:index + 2] != '=':
            return index
    return -1


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    found = []
    for hit in ASSIGN.finditer(clean, part.opening + 1, part.end):
        local, expr, store = hit[2], hit[3], hit[4]
        if '++' in expr or '--' in expr or _top_level_equals(expr) >= 0 or re.search(r'[A-Za-z_]\w*\s*\(', expr):
            continue
        equals = _top_level_equals(store)
        if equals < 0:
            continue
        left, right = store[:equals], store[equals + 1:]
        if re.search(rf'(?<![\w.>]){re.escape(local)}\b', left):
            continue
        uses = list(re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', right))
        everywhere = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', clean[part.opening + 1:part.end])]
        declaration = re.search(rf'(?m)^[ \t]*((?:unsigned\s+|signed\s+)?[A-Za-z_]\w*(?:\s*\*+|\s+\*+|\s+))\s*{re.escape(local)}\s*;[ \t]*\n', clean[part.opening + 1:part.end])
        if len(uses) < 2 or len(everywhere) != len(uses) + 2 or not declaration:
            continue
        kind = ' '.join(declaration[1].split()).replace(' *', ' *')
        kind = kind if kind.endswith('*') else kind + ' '
        base = part.opening + 1
        start = hit.start(4) + equals + 1
        edits = [(base + declaration.start(), base + declaration.end(), ''), (hit.start(), clean.index('\n', hit.end(3)) + 1, '')]
        for use in uses:
            edits.append((start + use.start(), start + use.end(), f'(({kind.strip()})({expr.strip()}))'))
        found.append((FAMILY, edit(source, edits)))
    return found[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 20}  # the registry: no caller wiring (registry.py)

"""Stack arrays declared in a block that opens after the call taking a scalar's address, so that scalar's slot comes first.

GCC 2.7.2 (stmt.c `expand_decl`): a non-volatile scalar that is not addressable at its declaration gets a pseudo
register there and, when `&scalar` is expanded later, `put_var_into_stack` gives it a frame slot *at that point*;
an array or struct gets its slot when its declaration's scope is entered (`assign_temp`). m2c declares every local
at the top of the function, so every array is allocated before any address-taken scalar, however late the scalar's
address is taken. A target whose frame holds the scalar *below* the arrays (the scalar's `&` came first in the
original, its arrays belonged to a later block) differs from that draft in nothing but those slot offsets:
five or so `s` rows, every other instruction equal. Opening a block after the call and declaring the arrays in
it (the whole use of the arrays stays inside) puts the slots in the target's order, with no `volatile` and no
padding local. (The allocation order is read from the compiler's source; the measured case was 5 -> 0 with the
join guard fixed, `boolean_guard_operands`.)
"""
import itertools
import re

from .integer_repair_support import IDENT, _address_taken, edit, view
from .pattern_repairs import close

FAMILY = 'late_aggregate_scope'
FAMILIES = (FAMILY,)
_ARRAY = re.compile(rf'(?m)^[ \t]*(?:(?:const|unsigned|signed|struct|union)\s+)*{IDENT}\s+({IDENT})\s*\[\s*\d+\s*\]\s*;[ \t]*\n')
_SCALAR = re.compile(rf'(?m)^[ \t]*(?:(?:const|unsigned|signed)\s+)*{IDENT}\s+({IDENT})\s*;')


def _depth_one(clean, opening, end):
    """The function body's own top level: positions whose brace depth (counting from the body's `{`) is 1."""
    depth, flat = 0, []
    for position in range(opening, end):
        char = clean[position]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        flat.append(depth)
    return flat


def _statement_start(clean, block, first):
    """Where the statement holding `first` begins inside `block` (an index of its `{`), or None."""
    brace = paren = 0
    start = block + 1
    for position in range(block + 1, first):
        char = clean[position]
        if char in '([':
            paren += 1
        elif char in ')]':
            paren -= 1
        elif char == '{':
            brace += 1
        elif char == '}':
            brace -= 1
            if brace == 0 and paren == 0:
                start = position + 1
        elif char == ';' and brace == 0 and paren == 0:
            start = position + 1
    if brace:
        return None
    while clean[start].isspace():
        start += 1
    return None if re.match(r'(?:else|case|default)\b', clean[start:]) else start


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm|__asm__|goto)\b', part.body):
        return []
    clean, flat = part.clean, _depth_one(part.clean, part.opening, part.end)

    def top(match):
        return flat[match.start() - part.opening] == 1 if part.opening <= match.start() < part.end else False

    arrays = [hit for hit in _ARRAY.finditer(clean, part.opening + 1, part.end) if top(hit)]
    scalars = [hit for hit in _SCALAR.finditer(clean, part.opening + 1, part.end)
               if top(hit) and not re.search(r'\b(?:volatile|register)\b', hit[0]) and _address_taken(part.body, hit[1])]
    if not arrays or not scalars:
        return []
    taken = []
    for scalar in scalars:
        site = re.search(rf'&\s*{re.escape(scalar[1])}\b', clean[scalar.end():part.end])
        if site and _address_taken(clean[scalar.end() + site.start():part.end], scalar[1]):
            taken.append(scalar.end() + site.start())
    if not taken:
        return []
    after = min(taken)
    moved, uses = [], []
    for array in arrays:
        found = [hit.start() for hit in re.finditer(rf'\b{re.escape(array[1])}\b', clean[array.end():part.end])]
        found = [array.end() + position for position in found]
        if not found or found[0] <= after:
            continue
        if len(re.findall(rf'\b{IDENT}\s+{re.escape(array[1])}\b', part.body)) != 1:
            continue
        moved.append(array)
        uses += found
    if not moved:
        return []
    first, last = min(uses), max(uses)
    # The innermost block holding every use, and the statement of the first use inside it.
    opens = []
    for position in range(part.opening, first):
        if clean[position] == '{':
            opens.append(position)
        elif clean[position] == '}':
            opens.pop()
    block = end = None
    for candidate in reversed(opens):
        stop = close(clean, candidate, '{', '}')
        if stop and stop > last:
            block, end = candidate, stop - 1
            break
    if block is None or block == part.opening:
        return []  # the function's own top level: nothing opens after the call
    start = _statement_start(clean, block, first)
    if start is None or start <= after:
        return []
    line = part.source.rfind('\n', 0, start) + 1
    own_line = not part.source[line:start].strip()
    indent = part.source[line:start] if own_line else ''
    close_line = part.source.rfind('\n', 0, end) + 1
    closing_own = not part.source[close_line:end].strip()
    # Slots go in declaration order, so the order inside the new block is a choice too: every order of up to three
    # arrays (a target's frame may hold them in either), the given one and its reverse beyond that.
    orders = list(itertools.permutations(moved)) if len(moved) <= 3 else [tuple(moved), tuple(reversed(moved))]
    out = []
    for order in orders:
        opening_text = f'{indent}{{\n' + ''.join(
            f'{indent}  ' + part.source[array.start():array.end()].strip() + '\n' for array in order)
        edits = [(array.start(), array.end(), '') for array in moved]
        edits += [(line if own_line else start,) * 2 + (opening_text,),
                  (close_line if closing_own else end,) * 2 + (f'{indent}}}\n',)]
        out.append((FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

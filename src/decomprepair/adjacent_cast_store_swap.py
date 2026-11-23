"""Two neighbouring stores through casts of one base, written in the other order.

A store of a constant and a store of a loaded value to two fields of one record (`*(s16 *)(p + 0x178) = 0;
*(u16 *)(p + 0x17A) = *(u16 *)(q + 0x24);`) have no dependence the compiler knows of, so the first scheduler orders
them by its own priorities and the statement order matters only through the loads' places. When the target has the
loaded value's store first, the swap is the whole difference (995 -> 785 in one 557-instruction function, KMC GCC
2.7.2, the zero store then sat after the load's own store as the target has it).

A proposal swaps two consecutive statements `*((T *) ADDR) = VALUE;` whose addresses are the same base plus different
literal offsets that do not overlap, when neither value calls a function or reads through
that base (a read through it could see the other store). One proposal per pair of neighbours, at most 12."""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'adjacent_cast_store_swap'
FAMILIES = (FAMILY,)
LIMIT = 12

_SIZE = {'s8': 1, 'u8': 1, 'char': 1, 'signed char': 1, 'unsigned char': 1, 's16': 2, 'u16': 2, 'short': 2,
         'unsigned short': 2, 's32': 4, 'u32': 4, 'int': 4, 'unsigned int': 4, 'unsigned': 4, 'f32': 4, 'float': 4,
         'void *': 4}
_STORE = re.compile(r'(?m)^(?P<indent>[ \t]*)\*\s*\(\s*\(\s*(?P<type>[A-Za-z_][\w ]*?(?: \*)?)\s*\*\s*\)\s*')
_OFFSET = re.compile(r'\b(0[xX][0-9a-fA-F]+|\d+)\b')
_BASE = re.compile(r'\(\s*char\s*\*\s*\)\s*([A-Za-z_]\w*)')
_HELPER = re.compile(r'\b(inline_fn\d*)\s*\(\s*\(\s*char\s*\*\s*\)\s*([A-Za-z_]\w*)\s*,\s*(0[xX][0-9a-fA-F]+|\d+)\s*\)')


def _address(text):
    """(base, offset) of a `(char *) base` plus a literal, or the same through one helper; else None."""
    helper = _HELPER.fullmatch(text.strip())
    if helper:
        return helper[2], int(helper[3], 0)
    plus = re.fullmatch(r'\(*\s*\(*\s*\(\s*char\s*\*\s*\)\s*([A-Za-z_]\w*)\s*\)*\s*(\+|- *\(-)\s*(0[xX][0-9a-fA-F]+|\d+)\s*\)*\)*', text.strip())
    if plus:
        return plus[1], int(plus[3], 0)
    return None


def _statements(part):
    """[(start, end, size, base, offset, value_text)] of the plain cast stores of the function, in order."""
    found = []
    for hit in _STORE.finditer(part.clean, part.opening, part.end):
        size = _SIZE.get(' '.join(hit['type'].split()))
        stop = close(part.clean, hit.end() - 1 - 0)
        # the cast `( T * )` was consumed: the operand runs to the `=` that ends the left side
        left = re.compile(r'[^;{}=]*?\)\s*=(?!=)').match(part.clean, hit.end())
        if not size or not left:
            continue
        semicolon = part.clean.find(';', left.end())
        if semicolon < 0:
            continue
        operand = part.clean[hit.end():left.end()]
        operand = re.sub(r'\)\s*=\s*$', '', operand)
        address = _address(operand)
        if not address:
            continue
        found.append((hit.start(), semicolon + 1, size, address[0], address[1], part.clean[left.end():semicolon]))
        del stop
    return found


def _unsafe(store, other):
    """True when `store`'s value calls a function, or reads through the base at a literal inside `other`'s bytes."""
    value = re.sub(r'\(\s*(?:s8|u8|s16|u16|s32|u32|f32|int|char|short|unsigned|signed|float|void)[\w *]*\)', '', store[5])
    if re.search(r'\w\s*\(', re.sub(r'\binline_fn\d*\s*\(', '(', value)):
        return True
    if not re.search(rf'\b{re.escape(other[3])}\b', store[5]):
        return False
    return any(other[4] <= int(m[1], 0) < other[4] + other[2] for m in _OFFSET.finditer(store[5]))


def variants(source, name):
    """Proposals: each pair of neighbouring independent stores through casts of one base, swapped."""
    part = view(source, name)
    if not part:
        return []
    stores, out = _statements(part), []
    for first, second in zip(stores, stores[1:]):
        if part.clean[first[1]:second[0]].strip() or first[3] != second[3]:
            continue
        if first[4] < second[4] + second[2] and second[4] < first[4] + first[2]:
            continue
        if any(_unsafe(mine, other) for mine, other in ((first, second), (second, first))):
            continue
        a = source[first[0]:first[1]]
        b = source[second[0]:second[1]]
        gap = source[first[1]:second[0]]
        out.append((FAMILY, edit(source, [(first[0], second[1], b + gap + a)])))
        if len(out) >= LIMIT:
            break
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 90}  # the registry: no caller wiring (registry.py)

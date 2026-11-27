"""A constant one block stores on both sides of a call, held by a local set in a one-shot loop at the block's head.

A literal stored before and after a call is one register in the target (`li $s2, 0x2000` once), because cse shares the
constant. With literals the first scheduler places that `li` itself, late, next to its first store:

    li $v0, 0x80          the target:   li $s2, 0x2000
    li $s2, 0x2000                      li $v0, 0x80

A local assigned the literal does not change that (a once-set pseudo is still launched next to its use), but the same
assignment inside `do { } while (0)` stays where it is written, ahead of the block's other constants:

    if (ready) {                                if (ready) {
        a = b = 0x80;                               do { size = 0x2000; } while (0);
        scale = 0x2000;               ->            a = b = 0x80;
        part = spawn();                             scale = size;
        part->scale = 0x2000;                       part = spawn();
    }                                               part->scale = size;
                                                }

Exact on an 81-instruction N64 object update built by SN's GCC (20 -> 0); the same local without the fence stayed at
20. Why the scheduler leaves the fenced set in place is a hypothesis (the loop notes bound its block), not confirmed in
the compiler's source.

Offered for a braced block that stores one literal, other than 0 or 1, with `=` at two or more places on both sides of
a call. Children: the fence at the block's head and before the first such store, with the local `s32` or `u16` (for a
literal that fits sixteen bits).
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'arm_constant_fence_local'
FAMILIES = (FAMILY,)
LIMIT = 8
_STORE = re.compile(r'(?<![=!<>+\-*/%&|^])=[ \t]*(0[xX][0-9a-fA-F]+|\d+)[uUlL]*[ \t]*;')
_CALL = re.compile(rf'\b(?!if\b|while\b|for\b|switch\b|return\b|sizeof\b){IDENT}\s*\(')
_DECLARATIONS = re.compile(r'(?:\s*(?:(?:register|unsigned|signed|const|volatile|struct)\s+)*[A-Za-z_]\w*'
                           r'(?:\s*\*+\s*|\s+)[A-Za-z_]\w*(?:\s*\[[^\]]*\])?\s*;)*')


def _blocks(body):
    """`(opening, closing)` offsets of every braced block in the function body, outermost first."""
    stack, found = [], []
    for at, char in enumerate(body):
        if char == '{':
            stack.append(at)
        elif char == '}' and stack:
            found.append((stack.pop(), at))
    return sorted(found)


def _fresh(source):
    name, number = 'size', 2
    while re.search(rf'\b{name}\b', source):
        name, number = f'size{number}', number + 1
    return name


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b|^\s*#', part.body, re.M):
        return []
    body, base = part.body, part.opening + 1
    local = _fresh(source + header)
    result, seen = [], set()
    # innermost blocks first: the block that holds the constant's uses, not every block around it
    for opening, closing in sorted(_blocks(body), key=lambda block: block[1] - block[0]):
        inside = body[opening + 1:closing]
        stores = {}
        for store in _STORE.finditer(inside):
            value = int(store[1], 0)
            if value > 1:
                stores.setdefault(value, []).append(store)
        for value, found in stores.items():
            if value in seen or len(found) < 2:
                continue
            if not any(call.start() > found[0].end() and call.start() < found[-1].start()
                       for call in _CALL.finditer(inside)):
                continue
            seen.add(value)
            literal = re.match(r'=[ \t]*([0-9a-fA-FxX]+)', found[0][0])[1]
            head = opening + 1 + _DECLARATIONS.match(inside).end()
            first = opening + 1 + found[0].start()
            before_first = max(body.rfind(mark, 0, first) for mark in ';{}') + 1
            indent = re.search(r'\n([ \t]*)\S', body[head:])
            indent = indent[1] if indent else '    '
            fence = f'\n{indent}do {{ {local} = {literal}; }} while (0);'
            replaced = [(base + opening + 1 + store.start(1), base + opening + 1 + store.end() - 1, local)
                        for store in found]
            for place in dict.fromkeys((head, before_first)):
                for kind in ('u16', 's32') if value <= 0xFFFF else ('s32',):
                    edits = [(part.opening + 1, part.opening + 1, f'\n    {kind} {local};'),
                             (base + place, base + place, fence)] + replaced
                    result.append((FAMILY, edit(source, edits)))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}

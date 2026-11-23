"""The mask of a word update held in the local the neighbouring arms keep their result in.

m2c gives the arms of a switch one scratch local for the value they store (`var_a0 = (temp & 0xFF81FFFF) | ...;
*(u32 *)(p + 0x5C) = var_a0;`, a dozen times) and a lone arm that stores the same kind of word straight from an
expression, `*(u32 *)(p + 0x5C) = (temp & 0xFF81FFFF) | (...);`. That arm has three block-local quantities: the word it
read, the mask constant, and the constant it stored beside the word (`li $v1, 0x46; sh`). GCC 2.7.2's local-alloc.c
orders a block of exactly three quantities with an exchange that compares quantity numbers instead of positions
(`qty_compare (1, 2)` after `EXCHANGE (0, 1)`), so the mask, born first, was allocated first and took `$v0`; the target
allocated the word first (`$v0`), the constant second and the mask last (`$a0`). A mask written into the shared local
(`var_a0 = 0xFF81FFFF;`, then `var_a0 = temp & var_a0; var_a0 |= ...;`) is a global pseudo: the block keeps two local
quantities, which are sorted properly, and the mask and the result take the register the other arms' result has, `$a0`.
On a 603-instruction N64 state machine (KMC GCC 2.7.2) the mask in the shared local took 180 to 135 and the result chain
135 to 120; the rest was the order of two loads.

A proposal needs a store `*(T *)(p + off) = (cast)((X & MASK) | REST);` (MASK a literal) whose word X was loaded from the
same address a few statements above, and a function-level integer local V that is assigned in three or more other
statements and appears in neither (the most-assigned one is used). Labelled `rmw_result_local`: `V = MASK;` before the load
of X, and the store written `V = X & V; V = V | (REST); *(T *)(p + off) = V;`, one child per such store.
"""
import re

from .csource import _blank, find

FAMILY = 'rmw_result_local'
FAMILIES = (FAMILY,)
LIMIT = 16

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?'
_STORE = re.compile(
    rf'(?m)^([ \t]*)(?P<lv>\*\(.+?\))\s*=\s*(?P<cast>\(\s*(?:u32|s32|unsigned int|unsigned|int)\s*\)\s*)?'
    rf'\(\s*\(\s*(?P<x>{_ID})\s*&\s*(?P<mask>{_NUM})\s*\)\s*\|\s*(?P<rest>.+)\)\s*;[ \t]*$')


def _locals(clean, opening, closing):
    head = clean[opening + 1:closing]
    out = {}
    for m in re.finditer(rf'(?m)^[ \t]*((?:unsigned\s+|signed\s+)*(?:u8|s8|u16|s16|u32|s32|int|long|short|unsigned))\s+({_ID})\s*;', head):
        if 'register' not in m[1] and 'volatile' not in m[1]:
            out[m[2]] = m[1]
    return out


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    closing = clean.rfind('}', 0, span[1])
    if opening < 0 or closing < opening or re.search(r'^\s*#', clean[span[0]:span[1]], re.M):
        return []
    body = clean[opening:closing]
    declared = _locals(clean, opening, closing)
    counts = {local: len(re.findall(rf'(?m)^\s*{local}\s*=(?!=)', body)) for local in declared}
    shared = sorted((local for local in declared if counts[local] >= 3), key=lambda local: (-counts[local], local))
    out = []
    for m in _STORE.finditer(clean, opening, closing):
        word, mask, rest = m['x'], m['mask'], m['rest'].strip()
        load = list(re.finditer(rf'(?m)^[ \t]*{word}\s*=\s*(?:\([^)]*\)\s*)?\(?\s*\*[^;\n]*;[ \t]*\n', clean[max(opening, m.start() - 600):m.start()]))
        if not load:
            continue
        loaded = max(opening, m.start() - 600) + load[-1].start()
        for var in shared:
            if re.search(rf'\b{var}\b', m[0]) or re.search(rf'(?m)^\s*{var}\s*=', clean[loaded:m.start()]):
                continue
            indent = m[1]
            first = f'{indent}{var} = {mask};\n'
            chain = (f'{indent}{var} = {word} & {var};\n{indent}{var} = {var} | ({rest});\n'
                     f'{indent}{m["lv"].strip()} = {var};')
            new = source[:loaded] + first + source[loaded:m.start()] + chain + source[m.end():]
            if new != source:
                out.append((FAMILY, new))
                break
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)

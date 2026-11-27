"""A pointer loaded into a local only to store it elsewhere and use it, read from its field a second time.

m2c names a loaded pointer once and uses the name for the store and for what follows:

    next = obj->current;            M2C_FIELD(obj, void **, 0x50) = next;
    obj->previous = next;           M2C_FIELD(next, s32 *, 0x4C) = 0;
    next->link = 0;

The target of an N64 effect update (SN GCC 2.8.1, `-G0 -mips3 -O2`, 78 instructions) loaded the pointer into `$v0`,
copied it (`move $v1,$v0`), stored `$v0` and cleared the word through `$v1`; with one local (or a chained assignment, a
read of the field just written, an inline helper) the copy is always merged away. Written as two reads of the same field,
the store first,

    obj->previous = obj->current;
    next = obj->current;
    next->link = 0;

cse reuses the first load's register for the second read and the copy stays (105 -> 0 from the draft's plain form,
125 -> 20 from the saved best). Why the copy then survives register allocation is a hypothesis; the judge decides.

The shapes, consecutive statements of one block, for a pointer local `t` that is used again afterwards, a pure load `E`
(a field of a name at a constant offset, or an address-named global) and a different memory lvalue `F` that does not
name `t`: `t = E; F = t;`, `F = E; t = F;`, `t = F = E;` and `F = t = E;`. Each becomes `F = E; t = E;`, which has the
same value. One child per site and, with several, one with all of them.
"""
import re

from .arm_block_support import brace_pairs, indentation, local_declaration, mentions, statements
from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'published_field_reread'
FAMILIES = (FAMILY,)
LIMIT = 8
_GLOBAL = r'D_[0-9A-Fa-f]{6,8}\w*'
_TYPE = r'[\w \t]+\*+'
_LOAD = re.compile(
    rf'M2C_FIELD\(\s*{IDENT}\s*,\s*{_TYPE}\s*,\s*-?{NUMBER}\s*\)'
    rf'|{IDENT}\s*->\s*{IDENT}'
    rf'|\*\s*\(\s*{_TYPE}\s*\)\s*\(\s*(?:\(\s*{_TYPE}\s*\)\s*)?{IDENT}\s*\+\s*{NUMBER}\s*\)'
    rf'|{_GLOBAL}')
_SET = re.compile(r'(?P<left>[^;{}=]*[^;{}=!<>+\-*/%&|^\s])\s*=(?!=)\s*(?P<right>[^;{}]+?)\s*;')
_MEMORY = re.compile(rf'M2C_FIELD\(|->|^\*|\[|^{_GLOBAL}$')
_IMPURE = re.compile(rf'\+\+|--|\bvolatile\b|=|(?<![\w.>])(?!M2C_FIELD\b|sizeof\b){IDENT}(?<![A-Z0-9_])\s*\(')


def _assignment(text):
    """(left, right) of a plain `left = right;` statement, where `right` may be a second assignment; None otherwise."""
    found = _SET.fullmatch(text)
    return (found['left'].strip(), found['right'].strip()) if found else None


def _site(first, second, pointer):
    """(local, load, lvalue) when the statement(s) have one of the shapes; `second` is None for a chained assignment."""
    one = _assignment(first)
    if not one:
        return None
    left, right = one
    if second is None:
        inner = _assignment(right + ';')
        if not inner:
            return None
        middle, load = inner
        local, lvalue = (left, middle) if pointer(left) else (middle, left)
    else:
        two = _assignment(second)
        if not two:
            return None
        if pointer(left) and two[1] == left:  # t = E; F = t;
            local, load, lvalue = left, right, two[0]
        elif pointer(two[0]) and two[1] == left:  # F = E; t = F;
            local, load, lvalue = two[0], right, left
        else:
            return None
    if not (pointer(local) and _LOAD.fullmatch(load) and _MEMORY.search(lvalue)) or lvalue == load:
        return None
    if _IMPURE.search(lvalue) or mentions(lvalue, local) or mentions(load, local):
        return None
    return local, load, lvalue


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []

    def pointer(text):
        if not re.fullmatch(IDENT, text):
            return False
        declared = local_declaration(clean, part.opening, text)
        return bool(declared and declared[1] and 'volatile' not in declared[0])

    spans = []
    for block_open, block_close in sorted(pairs.items()):
        units = list(statements(clean, block_open + 1, block_close))
        index = 0
        while index < len(units):
            a = units[index]
            first = clean[a[0]:a[1]].strip()
            found, end, width = _site(first, None, pointer), a[1], 1
            if not found and index + 1 < len(units):
                b = units[index + 1]
                found, end, width = _site(first, clean[b[0]:b[1]].strip(), pointer), b[1], 2
            if found and mentions(clean[end:part.end], found[0]):
                spans.append((a[0], end, found))
                index += width
            else:
                index += 1
    spans = spans[:LIMIT]

    def rewrite(span):
        start, end, (local, load, lvalue) = span
        return start, end, f'{lvalue} = {load};\n{indentation(source, start)}{local} = {load};'

    out = []
    for chosen in [[span] for span in spans] + ([spans] if len(spans) > 1 else []):
        text = edit(source, [rewrite(span) for span in chosen])
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 85}  # the registry: no caller wiring (registry.py)

"""A pointer minus an integer address, written for a byte difference: `(s32) p - (s32) &sym`.

`p - (s32) &sym` is pointer arithmetic: when `p` points at 4-byte elements the compiler scales the integer by 4
(`sll $v,$v,2` before the subtract) and the result is a pointer. The game computed a length in bytes, `subu` of the two
addresses with no scaling, which is `(s32) p - (s32) &sym`. m2c types the end address of a copy or cache-invalidate
range as `s32 *` (`temp = base + 0xF6`) and then writes the length as `temp - (s32) &start`, so three same-shaped
setup routines of a `gcc-2.7.2-kmc` game stood at 210 until the first operand carried the cast (the other three length
arguments, whose operands are `char` pointers, are not scaled and compile the same with or without it).

Offered for `P - (s32) X` (also `u32`, `int`, `unsigned int` casts) where P is an identifier declared in the file or the
function as a pointer or array of anything wider than a byte (a pointer to a pointer counts). One child per site
(`pointer_byte_difference`) and, with two or more, one with all of them (`pointer_byte_difference_all`). A hypothesis
(no shift right of the subtraction in the target is what supports it); the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'pointer_byte_difference'
FAMILY_ALL = 'pointer_byte_difference_all'
FAMILIES = (FAMILY, FAMILY_ALL)
LIMIT = 8
BYTE_TYPES = {'char', 's8', 'u8', 'void', 'M2C_UNK8', 'int8_t', 'uint8_t', 'Byte', 'u_char'}
QUALIFIERS = {'extern', 'static', 'const', 'register', 'volatile', 'struct', 'union', 'enum', 'signed', 'unsigned'}
INTEGER_CAST = r'\(\s*(?:s32|u32|int|unsigned\s+int|unsigned|long)\s*\)'
DIFFERENCE = re.compile(rf'(?<![\w.])(?P<lhs>{IDENT})\s*-\s*{INTEGER_CAST}\s*(?:&\s*)?{IDENT}\b')


def _declaration_start(clean, start):
    """Whether TYPE at START begins a declaration, not the left operand of a multiplication."""
    before = clean[:start].rstrip()
    if not before or before[-1] in ';{}(,':
        return True
    word = re.search(rf'({IDENT})$', before)
    return bool(word) and word[1] in QUALIFIERS


def _wide(clean, name):
    """Whether NAME is declared as a pointer or array of elements wider than one byte."""
    escaped = re.escape(name)
    for hit in re.finditer(rf'\b(?P<type>{IDENT})\s*(?P<stars>\*+)\s*{escaped}\b(?!\s*\()', clean):
        if _declaration_start(clean, hit.start()):
            return len(hit['stars']) > 1 or hit['type'] not in BYTE_TYPES
    for hit in re.finditer(rf'\b(?P<type>{IDENT})\s+{escaped}\s*\[', clean):
        if _declaration_start(clean, hit.start()) and hit['type'] not in QUALIFIERS:
            return hit['type'] not in BYTE_TYPES
    return False


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    found = []
    for hit in DIFFERENCE.finditer(clean, part.opening, part.end):
        if hit['lhs'] in QUALIFIERS or hit['lhs'] == 'return' or not _wide(clean, hit['lhs']):
            continue
        before = clean[:hit.start()].rstrip()
        if before.endswith(('*', '&', '->', '(s32)', '(u32)')):
            continue
        found.append((hit.start('lhs'), hit.start('lhs'), '(s32) '))
    found = found[:LIMIT]
    out = [(FAMILY, edit(source, [one])) for one in found]
    if len(found) > 1:
        out.append((FAMILY_ALL, edit(source, found)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}

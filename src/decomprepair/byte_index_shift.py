"""Offer a safe shift for an unsigned-byte index multiplied by a power of two.

In one KMC GCC 2.7.2 function, writing five byte-index strides as shifts improved O1 545 -> 520 without changing
O2 (45,965). One observation, not a match. The proven unsigned byte and shifts up to seven avoid signed overflow.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view
from .shared_float_equality_ladder import _MACRO

FAMILY = 'byte_index_shift'
FAMILIES = (FAMILY,)
_FIELD = rf'M2C_FIELD\(\s*{IDENT}\s*,\s*u8\s*\*\s*,\s*(?:0[xX][0-9A-Fa-f]+|\d+)\s*\)'
_PRODUCT = re.compile(rf'\(\s*(?P<field>{_FIELD})\s*\*\s*(?P<factor>0[xX][0-9A-Fa-f]+|\d+)\s*\)')


def variants(source, name, asm, header=''):
    part, span = view(source, name), find(source, name)
    macros = source + '\n' + (header or '')
    if (not part or not span or not _MACRO.search(macros)
            or len(re.findall(r'\btypedef\s+unsigned\s+char\s+u8\s*;', macros)) != 1
            or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+u8\b', macros)):
        return []
    changes = []
    for hit in _PRODUCT.finditer(part.clean, part.opening + 1, part.end):
        number = int(hit['factor'], 0)
        if number < 2 or number > 128 or number & (number - 1):
            continue
        shift = number.bit_length() - 1
        if not re.search(r'\bsll\s+\$\w+\s*,\s*\$\w+\s*,\s*(?:' + str(shift) + '|0x' + format(shift, 'x') + r')\b', asm or ''):
            continue
        field = source[hit.start('field'):hit.end('field')]
        changes.append((hit.start(), hit.end(), f'({field} << {shift})'))
        if len(changes) == 8:
            break
    out = [(FAMILY, edit(source, [change])) for change in changes]
    if len(changes) > 1:
        out.append((FAMILY, edit(source, changes)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',)}

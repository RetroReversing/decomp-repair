"""Remove an integer local that only adds a provable zero to a masked byte.

A KMC GCC 2.7.2 function's previous search left a constant live across a dispatch and added `local - constant`
to a masked byte. Removing that exact zero and its now-unused local improved the app judge from 6,870 to 6,660.
This is one observation, not a match. The assignment must be an unconditional top-level statement, the local must
have no other uses, and the masked operand must be an ordinary byte local so integer promotions are unchanged.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .join_tail_arm_split_repairs import _items

FAMILY = 'cancelled_constant_local'
FAMILIES = (FAMILY,)
_DECL = re.compile(rf'(?m)^[ \t]*s32\s+(?P<local>{IDENT})\s*;[ \t]*\n')
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'


def variants(source, name, header=''):
    part = view(source, name)
    macros = source + '\n' + (header or '')
    if not part or re.search(r'\b(?:goto|volatile|asm|__asm__)\b', part.body):
        return []
    if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s32|s8|u8)\s*;|(?m:^\s*#\s*(?:define|undef)\s+(?:s32|s8|u8)\b)', macros):
        return []
    closing = part.clean.rfind('}', part.opening, part.end)
    items = _items(part.clean, part.opening + 1, closing)
    if items is None:
        return []
    out = []
    for decl in _DECL.finditer(part.clean, part.opening + 1, closing):
        local = decl['local']
        if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+[^\n]*\b' + re.escape(local) + r'\b', macros):
            continue
        if len(re.findall(r'\b' + re.escape(local) + r'\b', part.body)) != 3:
            continue
        assignments = [(a, b, re.fullmatch(r'\s*' + re.escape(local) + r'\s*=\s*(' + _NUM + r')\s*;\s*',
                                          part.clean[a:b])) for a, b in items]
        assignments = [(a, b, m) for a, b, m in assignments if m]
        if len(assignments) != 1:
            continue
        first, last, assignment = assignments[0]
        constant = int(assignment[1], 0)
        pattern = re.compile(rf'(?P<masked>\(\s*(?P<byte>{IDENT})\s*&\s*{_NUM}\s*\))\s*\+\s*'
                             rf'\(\s*{re.escape(local)}\s*-\s*(?P<const>{_NUM})\s*\)')
        uses = list(pattern.finditer(part.clean, last, closing))
        if len(uses) != 1 or int(uses[0]['const'], 0) != constant:
            continue
        hit, byte = uses[0], uses[0]['byte']
        if (len(re.findall(r'\b(?:u8|s8)\s+' + re.escape(byte) + r'\s*;', part.body)) != 1
                or re.search(r'(?m)^\s*#\s*(?:define|undef)\s+[^\n]*\b' + re.escape(byte) + r'\b', macros)
                or re.search(r'/[*/]|#', source[hit.start():hit.end()])):
            continue
        out.append((FAMILY, edit(source, [(decl.start(), decl.end(), ''), (first, last, ''),
                                         (hit.start(), hit.end(), source[hit.start('masked'):hit.end('masked')])])))
    return out[:8]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}

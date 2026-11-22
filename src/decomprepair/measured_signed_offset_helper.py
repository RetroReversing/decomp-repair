"""Outline repeated signed offsets when KMC's target computes the bias first."""

import re

from .csource import find
from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'sll \$a1, \$s2, 1\naddu \$a1, \$a1, \$s2\nsll \$a1, \$a1, 2\n'
    rf'addu \$a1, \$a1, \$s2\nlui \$v0, %hi\((?P<base>{IDENT})\)\n'
    rf'lw \$v0, %lo\((?P=base)\)\(\$v0\)\nsll \$a1, \$a1, 3\n'
    r'addiu \$a1, \$a1, 396\njal (?P<call>' + IDENT + r')\naddu \$a1, \$v0, \$a1'
)


def variants(source, name, header, rows):
    if not 45 <= len(rows) <= 90:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    witness = _TARGET.search(target)
    if not witness or 'addiu $v0, $v0, 396' not in candidate:
        return []
    part = view(source, name)
    span = find(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if (not end or not span or re.search(r'\b(?:volatile|asm|__asm__|__LINE__|__repair_offset_helper)\b', part.clean)
            or re.search(r'\b__repair_offset_helper\b', header)):
        return []
    part.end = end
    sig = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*s32\s+(?P<index>{IDENT})\s*,\s*s32\s+{IDENT}\s*\)\s*$',
                    part.clean[:part.opening])
    if not sig or not re.search(rf'\bextern\s+s32\s+{re.escape(witness["base"])}\s*;', part.clean[:part.opening]):
        return []
    index = sig['index']
    if (re.search(rf'&\s*{re.escape(index)}\b|\b{re.escape(index)}\s*(?:=(?!=)|\+\+|--|[+*/-]=)', part.body)
            or re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+(?:{re.escape(index)}|{re.escape(witness["base"])})\b',
                         source + '\n' + header)):
        return []
    offset = re.compile(rf'\(\s*{re.escape(index)}\s*\*\s*0x68\s*\)\s*\+\s*0x18[Cc]\b')
    matches = list(offset.finditer(part.body))
    if len(matches) != 2 or len(re.findall(rf'\b{re.escape(witness["call"])}\s*\(', part.body)) < 2:
        return []
    for hit in matches:
        text = source[part.opening + 1 + hit.start():part.opening + 1 + hit.end()]
        if text != hit[0]:
            return []
    helper = ('static inline int __repair_offset_helper(s32 value)\n'
              '{ return (value * 0x68) + 0x18C; }\n\n')
    edits = [(span[0], span[0], helper)]
    edits += [(part.opening + 1 + hit.start(), part.opening + 1 + hit.end(),
               f'__repair_offset_helper({index})') for hit in matches]
    return [('measured_signed_offset_helper', edit(source, edits))]

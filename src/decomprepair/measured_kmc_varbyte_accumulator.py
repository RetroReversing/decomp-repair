"""Recover a full-width accumulator and return from a variable-byte decoder."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines

_UPDATE = re.compile(
    rf'\b(?P<acc>{IDENT})\s*=\s*\(\s*(?P=acc)\s*<<\s*7\s*\)\s*\+\s*'
    rf'\(\s*(?P<byte>{IDENT})\s*&\s*0[xX]7[fF]\s*\)\s*;'
)


def variants(source, name, header, rows):
    if not 15 <= len(rows) <= 35:
        return []
    changed = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (('addu $a0, $a0, $v0', 'or $a0, $a0, $v0') not in changed
            or ('move $v0, $a0', 'andi $v0, $a0, 255') not in changed):
        return []
    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.clean):
        return []
    matches = list(_UPDATE.finditer(part.body))
    if len(matches) != 1:
        return []
    hit = matches[0]
    acc = re.escape(hit['acc'])
    declaration = list(re.finditer(rf'\bu8\s+{acc}\s*;', part.body))
    returned = list(re.finditer(rf'\breturn\s+{acc}\s*;', part.body))
    signature = re.search(rf'\bu8\s+{re.escape(name)}\s*\([^;{{}}]*\)\s*$', part.clean[:part.opening])
    if (len(declaration) != 1 or len(returned) != 1 or not signature
            or re.search(rf'\b{re.escape(name)}\s*\(', header + '\n' + part.clean[:signature.start()])
            or re.search(rf'&\s*{acc}\b', part.body)):
        return []
    target = normalized_integer_lines(left for _, left, _ in rows if left)
    if not all(line in target for line in ('sll $a0, $a0, 7', 'andi $v0, $v1, 127')):
        return []
    start = part.opening + 1
    decl = declaration[0]
    fixed = edit(source, [(signature.start(), signature.start() + 2, 'u32'),
                          (start + decl.start(), start + decl.start() + 2, 'u32')])
    return [('measured_varbyte_accumulator', fixed)]

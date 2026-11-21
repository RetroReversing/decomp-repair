"""Regroup an observed packed-bit expression to recover KMC's register schedule."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = '''andi $v0, $s0, 31
beqz $v0, 96
sll $a0, $v0, 12
lw $s1, 24($s2)
sll $v0, $v0, 1
lui $v1, 256
or $v0, $v0, $v1
or $a0, $a0, $v0
sw $a0, ($s1)'''


def variants(source, name, header, rows):
    if len(rows) != 31:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changed = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (_TARGET not in target or ('sll $v0, $v0, 1', '') not in changed
            or ('', 'sll $v1, $a0, 1') not in changed):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    body = part.body
    expression = re.compile(
        rf'\(\(\s*(?P<value>{IDENT})\s*<<\s*(?:0[xX]0*[cC]|12)\s*\)\s*\|\s*'
        rf'\(\(\s*(?P=value)\s*\*\s*2\s*\)\s*\|\s*0[xX]0*1000000\s*\)\s*\)'
    )
    hit = expression.search(body)
    if not hit:
        return []
    value = hit['value']
    prefix = body[:hit.start()]
    mask = re.search(rf'\b{re.escape(value)}\s*=\s*{IDENT}\s*&\s*(?:0[xX]0*1[fF]|31)\s*;', prefix)
    if (not mask or not re.search(rf'\bs32\s+{re.escape(value)}\s*;', prefix)
            or re.search(rf'\b{re.escape(value)}\s*(?:[+*/&|^-]?=|\+\+|--)', prefix[mask.end():])
            or re.search(rf'&\s*{re.escape(value)}\b', body)
            or re.search(r'\bvolatile\b', body)):
        return []
    start = part.opening + 1
    fixed = edit(source, [(start + hit.start(), start + hit.end(),
                           f'((({value} << 12) | 0x01000000) | ({value} << 1))')])
    return [('measured_packed_bit_schedule', fixed)]

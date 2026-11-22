"""Recover a byte-count cursor from IDO's measured send loop."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'lw \$t2, (?P<count>\d+)\(\$sp\)\nlw \$t1, (?P<ptr>\d+)\(\$sp\)\n'
    rf'lw \$t3, (?P<size>\d+)\(\$sp\)\naddiu \$a2, \$zero, 8\n'
    rf'addu \$a0, \$t1, \$t2\njal (?P<callee>{IDENT})\nsubu \$a1, \$t3, \$t2'
)
_CANDIDATE = re.compile(
    r'sll \$t2, \$t1, 2\nsubu \$t2, \$t2, \$t1\nsll \$t2, \$t2, 2\n'
    r'addiu \$a2, \$zero, 8\naddu \$a0, \$t2, \$t3\n'
)


def variants(source, name, header, rows):
    if not 30 <= len(rows) <= 55:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    witness = _TARGET.search(target)
    if not witness or not _CANDIDATE.search(candidate):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__)\b', part.clean):
        return []
    part.end = end
    sig = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*(?P<type>{IDENT})\s*\*\s*(?P<arg>{IDENT})\s*,'
                    rf'\s*s32\s+(?P<size>{IDENT})\s*,\s*s32\s+{IDENT}\s*\)\s*$', part.clean[:part.opening])
    if not sig:
        return []
    decls = list(re.finditer(rf'\b{re.escape(sig["type"])}\s*\*\s*(?P<cursor>{IDENT})\s*;', part.body))
    if len(decls) != 1:
        return []
    decl, cursor = decls[0], decls[0]['cursor']
    assignments = list(re.finditer(rf'\b{re.escape(cursor)}\s*=\s*{re.escape(sig["arg"])}\s*;', part.body))
    call = re.search(rf'\b{re.escape(witness["callee"])}\s*\(\s*{re.escape(cursor)}\s*\+\s*(?P<count>{IDENT})\s*,'
                     rf'\s*{re.escape(sig["size"])}\s*-\s*(?P=count)\s*,\s*8\s*\)', part.body)
    if (len(assignments) != 1 or not call or len(re.findall(rf'\b{re.escape(cursor)}\b', part.body)) != 3
            or not re.search(rf'\bu32\s+{re.escape(call["count"])}\s*;', part.body)
            or re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+(?:{re.escape(cursor)}|{re.escape(sig["type"])})\b',
                         source + '\n' + header)):
        return []
    original = source[part.opening + 1:part.end - 1]
    if '/*' in original or '//' in original or '#' in original:
        return []
    start = part.opening + 1
    assign = assignments[0]
    fixed = edit(source, [(start + decl.start(), start + decl.end(), f'char *{cursor};'),
                          (start + assign.start(), start + assign.end(), f'{cursor} = (char *) {sig["arg"]};')])
    return [('measured_ido_byte_cursor', fixed)]

"""Restore a missing return counter in a simple linked-list walk."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .mips import normalized_integer_lines

_BODY = re.compile(
    rf'\s*void\s*\*\s*(?P<cursor>{IDENT})\s*;\s*'
    rf'(?P=cursor)\s*=\s*\*\s*(?P<head>{IDENT})\s*;\s*'
    rf'if\s*\(\s*(?P=cursor)\s*!=\s*NULL\s*\)\s*\{{\s*do\s*\{{\s*'
    rf'(?P<step>(?P=cursor)\s*=\s*M2C_FIELD\(\s*(?P=cursor)\s*,\s*void\s*\*\*\s*,\s*{NUMBER}\s*\)\s*;)'
    rf'\s*\}}\s*while\s*\(\s*(?P=cursor)\s*!=\s*NULL\s*\)\s*;\s*\}}\s*'
)


def variants(source, name, header, rows):
    part = view(source, name)
    if not part or re.search(r'\bvolatile\b', part.clean):
        return []
    body = _BODY.fullmatch(part.body)
    if not body:
        return []
    definition = re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\*\*\s*'
                           rf'{re.escape(body["head"])}\s*\)\s*$', part.clean[:part.opening])
    if (not definition or re.search(rf'\b{re.escape(name)}\s*\(', header)
            or re.search(rf'\b{re.escape(name)}\s*\(', part.clean[:definition.start()])):
        return []
    if re.search(r'\b__repair_count\b', part.clean + '\n' + header):
        return []
    changed = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (('move $v0, $zero', 'nop') not in changed
            or ('addiu $v0, $v0, 1', 'nop') not in changed):
        return []
    start = part.opening + 1
    fixed = edit(source, [(definition.start(), definition.start() + 4, 'u32'),
                          (start, start, '\n    u32 __repair_count = 0;'),
                          (start + body.start('step'), start + body.start('step'), '__repair_count++;\n            '),
                          (part.end - 1, part.end - 1, '    return __repair_count;\n')])
    return [('measured_linked_list_count', fixed)]

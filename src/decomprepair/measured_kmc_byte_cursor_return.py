"""Try advancing a byte cursor at its read when the target schedules it early."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines

_READ = re.compile(rf'\b(?P<byte>{IDENT})\s*=\s*\*\s*(?P<cursor>{IDENT})\s*;')


def variants(source, name, header, rows):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.clean):
        return []
    hits = list(_READ.finditer(part.body))
    if len(hits) != 1:
        return []
    hit = hits[0]
    cursor = re.escape(hit['cursor'])
    sig = part.clean[:part.opening]
    if not re.search(rf'\b(?:u8|unsigned\s+char)\s*\*\s*{cursor}\b', sig):
        return []
    returns = list(re.finditer(rf'\breturn\s+{cursor}\s*\+\s*1\s*;', part.body))
    if len(returns) != 1 or returns[0].start() <= hit.end():
        return []
    ret = returns[0]
    if (re.search(rf'\b{cursor}\b', part.body[hit.end():ret.start()])
            or len(re.findall(rf'\b{cursor}\b', part.body)) != 2
            or re.search(rf'\b(?:u8|unsigned\s+char)\s+{re.escape(hit["byte"])}\s*\[', part.body)):
        return []
    changed = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (('addiu $a1, $a1, 1', '') not in changed
            or ('move $v0, $a1', 'addiu $v0, $a1, 1') not in changed):
        return []
    target = normalized_integer_lines(left for _, left, _ in rows if left)
    if 'lbu $v0, ($a1)' not in target and 'lbu $v0, 0($a1)' not in target:
        return []
    start = part.opening + 1
    fixed = edit(source, [(start + hit.end() - 1, start + hit.end() - 1, '++'),
                          (start + ret.start(), start + ret.end(), f'return {hit["cursor"]};')])
    return [('measured_byte_cursor_return', fixed)]

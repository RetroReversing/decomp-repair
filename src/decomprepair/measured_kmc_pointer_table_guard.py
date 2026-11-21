"""Recover an indexed pointer store and signed masked comparison in KMC output."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_STORE = re.compile(
    rf'\*\(&(?P<global>{IDENT})\s*\+\s*\(\((?P<index>{IDENT})\s*&\s*0xFFFF\)\s*\*\s*0x64\)\)\s*=\s*(?P<value>{IDENT})\s*;'
)
_CONDITION = re.compile(rf'\(\((?P<local>{IDENT})\s*&\s*7\)\s*<\s*5\)')


def variants(source, name, header, rows):
    if not 40 <= len(rows) <= 80:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (('slti $v0, $v0, 5', 'sltiu $v0, $v0, 5') not in changes
            or ('sll $v0, $v0, 2', 'sll $v0, $v0, 4') not in changes
            or not re.search(r'andi \$v0, \$v1, 7\nslti \$v0, \$v0, 5', target)):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    body = part.body
    condition = _CONDITION.search(body)
    store = _STORE.search(body)
    if not condition or not store or condition.start() >= store.start():
        return []
    local, symbol = condition['local'], store['global']
    if (not re.search(rf'\bu16\s+{re.escape(local)}\s*;', body)
            or not re.search(rf'\b{re.escape(local)}\s*=\s*M2C_FIELD\([^;]*\bu16\s*\*\s*,', body)
            or not re.search(rf'\bextern\s+M2C_UNK\s+{re.escape(symbol)}\s*;', part.clean[:part.opening])
            or not re.search(rf'\bvoid {re.escape(name)}\(void \*{re.escape(store["value"])}\)\s*$', part.clean[:part.opening])
            or re.search(r'\bvolatile\b', part.clean[part.opening:part.end])
            or not re.search(rf'sll \$v0, \$v0, 2\nlui \$at, %hi\({re.escape(symbol)}\)\n'
                             rf'addu \$at, \$at, \$v0\nsw \$s0, %lo\({re.escape(symbol)}\)\(\$at\)', target)):
        return []
    start = part.opening + 1
    compare = f'(((s16){local} & 7) < 5)'
    address = f'*(void **)((char *)&{symbol} + (({store["index"]} & 0xFFFF) * 0x64)) = {store["value"]};'
    fixed = edit(source, [(start + condition.start(), start + condition.end(), compare),
                          (start + store.start(), start + store.end(), address)])
    return [('measured_signed_guard_pointer_stride', fixed)]

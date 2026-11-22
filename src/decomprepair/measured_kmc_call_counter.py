"""Move a loop-counter initialization past a call when the target schedules it there."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_SOURCE = re.compile(
    rf'(?P<init>(?P<counter>{IDENT})\s*=\s*0\s*;)\s*'
    rf'(?P<guard>if\s*\(\s*(?P<call>{IDENT})\s*\(\s*\(char\s*\*\)\s*&(?P<base>{IDENT})\s*\+\s*{NUMBER}\s*\)\s*!=\s*0\s*\)\s*\{{)'
)


def variants(source, name, header, rows):
    if not 25 <= len(rows) <= 29:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if ('move $s1, $zero', 'nop') not in changes:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    body = part.body
    draft = _SOURCE.search(body)
    if not draft:
        return []
    counter, call = draft['counter'], draft['call']
    guard_end = close(body, draft.end('guard') - 1, '{', '}')
    if (not guard_end or re.search(rf'\b{re.escape(counter)}\b', body[guard_end:])
            or not re.search(rf'\bs32\s+{re.escape(counter)}\s*;', body[:draft.start()])
            or re.search(rf'(?:&|\+\+|--)\s*{re.escape(counter)}\b', body)
            or re.search(r'\bvolatile\b', part.clean[part.opening:part.end])
            or not re.search(rf'jal {re.escape(call)}\naddiu \$a0, \$a0, %lo\({IDENT}\)\n'
                             r'beqz \$v0, \d+\nmove \$s1, \$zero', target)):
        return []
    start = part.opening + 1
    fixed = edit(source, [(start + draft.start('init'), start + draft.end('init'), ''),
                          (start + draft.end('guard'), start + draft.end('guard'), '\n            ' + draft['init'])])
    return [('measured_call_then_counter_init', fixed)]

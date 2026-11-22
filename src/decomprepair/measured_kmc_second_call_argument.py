"""Supply a constant second call argument evidenced in the KMC target."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(rf'move \$a0, \$s0\njal (?P<call>{IDENT})\naddiu \$a1, \$zero, 3')


def variants(source, name, header, rows):
    if not 20 <= len(rows) <= 200:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    observed = _TARGET.search(target)
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if not observed or ('addiu $a1, $zero, 3', '') not in changes:
        return []
    call = observed['call']
    if not any(left == f'jal {call}' and right == '' for left, right in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    if (re.search(rf'\b{re.escape(call)}\b', _blank(header or ''))
            or not re.search(rf'\bs32\s+{re.escape(call)}\s*\(\s*\)\s*;', part.clean[:part.opening])):
        return []
    calls = list(re.finditer(rf'\b{re.escape(call)}\s*\(\s*(?P<arg>{IDENT})\s*\)', part.body))
    if len(calls) != 1 or len(re.findall(rf'\b{re.escape(call)}\s*\(', part.body)) != 1:
        return []
    hit = calls[0]
    start = part.opening + 1
    fixed = edit(source, [(start + hit.end('arg'), start + hit.end('arg'), ', 3')])
    return [('measured_constant_second_call_argument', fixed)]

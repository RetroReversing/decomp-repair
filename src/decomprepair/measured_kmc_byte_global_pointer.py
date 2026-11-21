"""Keep the address of a byte global for an observed KMC update and call."""

import re

from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'addiu \$sp, \$sp, -24\nsw \$ra, 16\(\$sp\)\n'
    rf'lui \$v1, %hi\((?P<global>{IDENT})\)\naddiu \$v1, \$v1, %lo\((?P=global)\)\n'
    r'lbu \$v0, \(\$v1\)\naddiu \$v0, \$v0, -(?P<amount>\d+)\nsb \$v0, \(\$v1\)\n'
    rf'jal (?P<call>{IDENT})\naddiu \$a0, \$zero, (?P<argument>\d+)\n'
    r'lw \$ra, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 24'
)
_SOURCE = _shape('@global -= @amount; @call(@argument);', numbers=('amount', 'argument'))


def variants(source, name, header, rows):
    if len(rows) != 13:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    observed = _TARGET.fullmatch(target)
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if not observed or (f'addiu $v1, $v1, %lo({observed["global"]})', '') not in changes:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    if (not draft or draft['global'] != observed['global'] or draft['call'] != observed['call']
            or integer(draft['amount']) != int(observed['amount'])
            or integer(draft['argument']) != int(observed['argument'])
            or not re.search(rf'\bextern\s+u8\s+{re.escape(draft["global"])}\s*;', part.clean[:part.opening])
            or not re.search(rf'\bvoid {re.escape(name)}\(void\)\s*$', part.clean[:part.opening])
            or re.search(r'\bvolatile\b|\b__repair_byte_ptr\b', part.clean)):
        return []
    body = (f'\n    u8 *__repair_byte_ptr;\n\n    __repair_byte_ptr = &{draft["global"]};\n'
            f'    *__repair_byte_ptr -= {draft["amount"]};\n    {draft["call"]}({draft["argument"]});\n')
    fixed = edit(source, [(part.opening + 1, part.end - 1, body)])
    return [('measured_byte_global_pointer', fixed)]

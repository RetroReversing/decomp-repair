"""Retain a measured global ring pointer across the guarded update."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    rf'lui \$a1, %hi\((?P<ring>{IDENT})\)\nlw \$a1, %lo\((?P=ring)\)\(\$a1\)\n'
    r'addiu \$sp, \$sp, -24\nbeqz \$a1, [^\n]+\nsw \$ra, 16\(\$sp\)\n'
    r'lw \$a0, 8\(\$a1\)\nlw \$v1, 16\(\$a1\)\nslt \$v0, \$a0, \$v1'
)


def variants(source, name, header, rows):
    if not 35 <= len(rows) <= 65:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    witness = _TARGET.search(target)
    if not witness:
        return []
    ring = witness['ring']
    if (target.count(f'%hi({ring})') != 1 or 'sw $a0, ($v1)' not in target
            or 'sw $v0, 8($a1)' not in target or 'lw $v1, ($a1)' not in target):
        return []
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if candidate.count(f'%hi({ring})') != 2 or 'sw $v0, 8($a0)' not in candidate:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__|__repair_ring)\b', part.clean):
        return []
    part.end = end
    if (not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\)\s*$', part.clean[:part.opening])
            or not re.search(rf'\bextern\s+void\s*\*\s*{re.escape(ring)}\s*;', part.clean[:part.opening])
            or re.search(rf'(?m)^\s*#\s*(?:define|undef)\s+{re.escape(ring)}\b', source + '\n' + header)
            or re.search(r'\b__repair_ring\b', header)):
        return []
    guard = re.search(rf'\bif\s*\(\s*{re.escape(ring)}\s*!=\s*NULL\s*\)', part.body)
    if not guard or not re.fullmatch(rf'\s*(?:s32\s+{IDENT}\s*;\s*)+', part.body[:guard.start()]):
        return []
    uses = list(re.finditer(rf'\b{re.escape(ring)}\b', part.body))
    if len(uses) < 6 or re.search(rf'\b{re.escape(ring)}\s*=(?!=)|&\s*{re.escape(ring)}\b', part.body):
        return []
    original = source[part.opening + 1:part.end - 1]
    if '/*' in original or '//' in original or '#' in original:
        return []
    start = part.opening + 1
    changes = [(start, start, '\n    void *__repair_ring;'),
               (start + guard.start(), start + guard.start(), f'__repair_ring = {ring};\n    ')]
    changes += [(start + use.start(), start + use.end(), '__repair_ring') for use in uses]
    # The target proves the saved pointer survives the indirect store; if it
    # aliases the global, this intentionally follows target rather than draft.
    return [('measured_ring_global_capture', edit(source, changes))]

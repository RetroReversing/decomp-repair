"""Recover directly squared vector fields when KMC schedules later reads early."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = '''lw $v0, ($a0)
mult $v0, $v0
mflo $v0
sw $v0, ($a1)
nop
lw $v0, 4($a0)
mult $v0, $v0
mflo $v0
sw $v0, 4($a1)
nop
lw $v0, 8($a0)
mult $v0, $v0
mflo $v0
nop
nop
jr $ra
sw $v0, 8($a1)'''
_SOURCE = _shape('''
    s32 @first; s32 @second; s32 @third;
    @first = M2C_FIELD(@src, s32 *, 0);
    M2C_FIELD(@dst, s32 *, 0) = (s32) (@first * @first);
    @second = M2C_FIELD(@src, s32 *, 4);
    M2C_FIELD(@dst, s32 *, 4) = (s32) (@second * @second);
    @third = M2C_FIELD(@src, s32 *, 8);
    M2C_FIELD(@dst, s32 *, 8) = (s32) (@third * @third);
''')


def variants(source, name, header, rows):
    if len(rows) != 20:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    changes = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    if (target != _TARGET or ('', 'nop') not in changes
            or ('lw $v0, 4($a0)', '') not in changes
            or ('lw $v0, 8($a0)', '') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    sig = re.search(rf'\bvoid {re.escape(name)}\(void \*({IDENT}), void \*({IDENT})\)\s*$', part.clean[:part.opening])
    if (not draft or not sig or sig.groups() != (draft['src'], draft['dst'])
            or len(set(draft.groupdict().values())) != 5
            or re.search(r'\bvolatile\b', part.clean[part.opening:part.end])):
        return []
    lines = []
    for offset in (0, 4, 8):
        field = f'M2C_FIELD({draft["src"]}, s32 *, {offset})'
        lines.append(f'    M2C_FIELD({draft["dst"]}, s32 *, {offset}) = (s32) ({field} * {field});')
    fixed = edit(source, [(part.opening + 1, part.end - 1, '\n' + '\n'.join(lines) + '\n')])
    return [('measured_direct_vector_squares', fixed)]

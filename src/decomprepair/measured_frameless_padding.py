"""Try a measured unused frame when the draft has no stack frame at all."""

import re

from .integer_repair_support import edit, view
from .mips import normalized_integer_lines

BRANCH = re.compile(r'(?P<prefix>b(?:eq|ne|eqz|nez|lez|gtz|ltz|gez)\s+[^\n]*,\s*)(?P<target>\d+)$')


def variants(source, name, header, rows):
    target, candidate = [list(normalized_integer_lines(row[side] for row in rows if row[side])) for side in (1, 2)]
    if len(target) != len(candidate) + 1 or len(candidate) < 3:
        return []
    start = re.fullmatch(r'addiu \$sp, \$sp, -(?P<size>\d+)', target[0])
    if not start:
        return []
    size = int(start['size'])
    if not 8 <= size <= 32 or size % 8 or target[-2:] != ['jr $ra', f'addiu $sp, $sp, {size}']:
        return []
    if candidate[-2:] != ['jr $ra', 'nop'] or any('$sp' in line or re.match(r'jalr?\b', line) for line in candidate):
        return []
    # The single prologue instruction shifts every internal destination by four
    # bytes; no instruction other than branch destinations and the return delay
    # slot may differ. This keeps the proposal small and avoids guessing layout.
    trial = target[1:-1] + ['nop']
    for left, right in zip(trial, candidate):
        if left == right:
            continue
        a, b = BRANCH.fullmatch(left), BRANCH.fullmatch(right)
        if not a or not b or a['prefix'] != b['prefix'] or int(a['target']) != int(b['target']) + 4:
            return []
    part = view(source, name)
    if not part or re.search(r'\b__repair_unused_frame\b', part.clean + '\n' + header):
        return []
    if re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    return [('measured_frameless_padding', edit(source, [
        (part.opening + 1, part.opening + 1, f'\n    s32 __repair_unused_frame[{size // 4}];'),
    ]))]

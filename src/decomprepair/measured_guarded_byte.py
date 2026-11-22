"""Recover a measured signed-byte check after a bounded cursor advance."""

import re

from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines

BODY = _shape('''
    u32 @cursor;
    @cursor = @callee();
    if (@cursor >= @end) {
        *@flag = 0;
        @cursor = @end;
    } else if (*(s32 *)@cursor == @marker) {
        *@flag = 0;
    } else {
        *@flag = 1;
    }
    return @cursor;
''', numbers=('marker',))

TARGET = re.compile(
    rf'jal (?P<callee>{IDENT})\nmove \$s1, \$a2\nmove \$a0, \$v0\n'
    rf'sltu \$v0, \$a0, \$s0\nbnez \$v0, \d+\naddiu \$v0, \$zero, (?P<marker>\d+)\n'
    rf'sb \$zero, \(\$s1\)\nj [^\n]+\nmove \$a0, \$s0\n'
    rf'lb \$v1, \(\$a0\)\nbne \$v1, \$v0, \d+\naddiu \$v0, \$zero, 1'
)


def variants(source, name, header, rows):
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    if not (match := TARGET.search(target)):
        return []
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if ('lb $v1, ($a0)', 'lw $v1, ($a0)') not in changes:
        return []
    part = view(source, name)
    if not part:
        return []
    m = BODY.fullmatch(' '.join(part.body.split()))
    if not m or m['callee'] != match['callee'] or integer(m['marker']) != int(match['marker']):
        return []
    if not 0 <= integer(m['marker']) <= 127:
        return []
    signature = re.search(rf'\bu32\s+{re.escape(name)}\s*\(\s*s32\s+(?P<arg>{IDENT})\s*,\s*'
                          rf'u32\s+{m["end"]}\s*,\s*s8\s*\*\s*{m["flag"]}\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature or len({signature['arg'], m['cursor'], m['end'], m['flag'], m['callee']}) != 5:
        return []
    context = part.clean + '\n' + header
    if re.search(rf'(?m)^\s*#\s*define\s+(?:{m["cursor"]}|{m["end"]}|{m["flag"]}|{m["callee"]})\b', context):
        return []
    if not re.search(rf'\bu32\s+{m["callee"]}\s*\(\s*\)\s*;', part.clean[:part.opening] + '\n' + header):
        return []
    byte = re.search(rf'\*\(s32\s*\*\)\s*{m["cursor"]}\b', part.body)
    assignment = re.search(rf'\b{m["cursor"]}\s*=\s*{m["end"]}\s*;', part.body)
    if not byte or not assignment:
        return []
    # The single-iteration scope preserves the assignment but gives this KMC
    # compiler the target's saved-register order (measured on a cursor check).
    start = part.opening + 1
    return [('measured_guarded_byte', edit(source, [
        (start + byte.start(), start + byte.end(), f'*(s8 *){m["cursor"]}'),
        (start + assignment.start(), start + assignment.end(), f'do {{ {m["cursor"]} = {m["end"]}; }} while (0);'),
    ]))]

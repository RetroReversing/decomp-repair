"""Recover the measured two-word command cursor after a call."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_SOURCE = _shape('''
    void *@first; void *@second;
    @first = @pull();
    ((@record*)@first)->field_0 = 0x0D000000;
    @second = @first + 8;
    ((@record*)@first)->field_8 = 0x062E0000;
    M2C_FIELD(@second, s32 *, 4) = (s32) M2C_FIELD(@global, s32 *, 0x54);
    return @second + 8;
''')
_TARGET = re.compile(
    rf'jal (?P<pull>{IDENT})\nnop\nmove \$v1, \$v0\nmove \$a0, \$v1\n'
    rf'lui \$v0, 3328\nsw \$v0, \(\$a0\)\nlui \$a0, %hi\((?P<global>{IDENT})\)\n'
    rf'lw \$a0, %lo\((?P=global)\)\(\$a0\)\naddiu \$v1, \$v1, 8\n'
    rf'lui \$v0, 1582\nsw \$v0, \(\$v1\)\nlw \$a0, 84\(\$a0\)\n'
    rf'addiu \$v0, \$v1, 8\nlw \$ra, 16\(\$sp\)\nsw \$a0, 4\(\$v1\)'
)


def variants(source, name, header, rows):
    if not 18 <= len(rows) <= 30:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    witness = _TARGET.search(target)
    if not witness:
        return []
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if 'sw $v0, 8($v1)' not in candidate or 'addiu $v0, $v1, 16' not in candidate:
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or (re.search(r'\b(?:volatile|asm|__asm__|__LINE__|__repair_cmd)\b', part.clean)
                   or re.search(r'\b__repair_cmd\b', header)):
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    if (not draft or draft['global'] != witness['global'] or draft['pull'] != witness['pull']
            or not re.search(rf'\bvoid\s*\*\s*{re.escape(name)}\s*\(\s*void\s*\)\s*$',
                             part.clean[:part.opening])
            or not re.search(rf'\bextern\s+void\s*\*\s*{re.escape(draft["global"])}\s*;',
                             part.clean[:part.opening])):
        return []
    typedef = (rf'typedef\s+struct\s*{{\s*int\s+field_0\s*;\s*unsigned\s+char\s+pad_4\s*\[\s*4\s*\]\s*;'
               rf'\s*int\s+field_8\s*;\s*}}\s*{re.escape(draft["record"])}\s*;')
    if not re.search(typedef, part.clean[:part.opening]):
        return []
    original = source[part.opening + 1:part.end - 1]
    if '/*' in original or '//' in original or '#' in original:
        return []
    body = ('\n    typedef struct { u32 w0, w1; } __repair_cmd;\n'
            f'    __repair_cmd *cmd = {draft["pull"]}();\n'
            '    __repair_cmd *first;\n\n'
            '    first = cmd++;\n    *(u32 *) first = 0x0D000000;\n'
            '    cmd->w0 = 0x062E0000;\n'
            f'    cmd->w1 = *(u32 *) ((char *) {draft["global"]} + 0x54);\n'
            '    return cmd + 1;\n')
    return [('measured_command_record_cursor', edit(source, [(part.opening + 1, part.end - 1, body)]))]

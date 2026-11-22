"""Recover a forwarded argument and measured two-word command cursor."""

import re

from .integer_repair_support import edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_SOURCE = _shape('''
    void *@first; void *@second;
    ((@record*)@dest)->field_0 = 0x020004E0;
    ((@record*)@dest)->field_4 = 0x2E0;
    @first = M2C_FIELD(M2C_FIELD(@global, void **, 0x3C), void *(**)(void *), 4)(@dest + 8);
    @second = @first + 8;
    M2C_FIELD(@first, s32 *, 0) = 0x0C007FFF;
    M2C_FIELD(@first, s32 *, 4) = 0x07C004E0;
    M2C_FIELD(@second, s32 *, 4) = 0x09300650;
    M2C_FIELD(@first, s32 *, 8) = 0x0C007FFF;
    return @second + 8;
''')
_TARGET = re.compile(
    r'lw \$v0, 60\(\$v1\)\nlw \$v0, 4\(\$v0\)\njalr \$v0\naddiu \$a1, \$a1, 8\n'
    r'move \$v1, \$v0\nmove \$a1, \$v1\naddiu \$v1, \$v1, 8\n'
    r'lui \$a2, 3072\nori \$a2, \$a2, 32767\n'
    r'lui \$a0, 1984\nori \$a0, \$a0, 1248\n'
    r'lui \$a3, 2352\nori \$a3, \$a3, 1616\n'
    r'addiu \$v0, \$v1, 8\nsw \$a2, \(\$a1\)\nsw \$a0, 4\(\$a1\)\n'
    r'sw \$a2, \(\$v1\)\nlw \$ra, 16\(\$sp\)\nsw \$a3, 4\(\$v1\)'
)


def variants(source, name, header, rows):
    if not 25 <= len(rows) <= 40:
        return []
    target_lines = normalized_integer_lines(left for _, left, _ in rows if left)
    target = '\n'.join(target_lines)
    witness = _TARGET.search(target)
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if not witness or 'jalr $v0\naddiu $a0, $a1, 8' not in candidate:
        return []
    before_call = target_lines[:next(i for i, line in enumerate(target_lines) if line == 'jalr $v0')]
    if any(re.match(r'(?:move|lui|lw|addiu|addu|andi|ori) \$a0,', line) for line in before_call):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if (not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__|__repair_cmd)\b', part.clean)
            or re.search(r'\b__repair_cmd\b', header)):
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    if not draft:
        return []
    sig = re.search(rf'\bs32\s+{re.escape(name)}\s*\(\s*s32\s+(?P<arg>\w+)\s*,'
                    rf'\s*void\s*\*\s*{re.escape(draft["dest"])}\s*\)\s*$', part.clean[:part.opening])
    if (not sig or sig['arg'] in ('__repair_p', '__repair_out', '__repair_first', '__repair_second')
            or not re.search(rf'\bextern\s+void\s*\*\s*{re.escape(draft["global"])}\s*;',
                             part.clean[:part.opening])
            or f'%hi({draft["global"]})' not in target):
        return []
    typedef = (rf'typedef\s+struct\s*{{\s*int\s+field_0\s*;\s*int\s+field_4\s*;\s*}}'
               rf'\s*{re.escape(draft["record"])}\s*;')
    if not re.search(typedef, part.clean[:part.opening]):
        return []
    original = source[part.opening + 1:part.end - 1]
    if '/*' in original or '//' in original or '#' in original:
        return []
    body = ('\n    typedef struct { u32 w0, w1; } __repair_cmd;\n'
            f'    __repair_cmd *__repair_p = {draft["dest"]}, *__repair_out;\n\n'
            '    __repair_p->w0 = 0x020004E0;\n    __repair_p->w1 = 0x2E0;\n'
            f'    __repair_out = M2C_FIELD(M2C_FIELD({draft["global"]}, void **, 0x3C), '
            f'void *(**)(s32, void *), 4)({sig["arg"]}, __repair_p + 1);\n'
            '    { __repair_cmd *__repair_first = __repair_out++;\n'
            '      __repair_first->w0 = 0x0C007FFF; __repair_first->w1 = 0x07C004E0; }\n'
            '    { __repair_cmd *__repair_second = __repair_out++;\n'
            '      __repair_second->w0 = 0x0C007FFF; __repair_second->w1 = 0x09300650; }\n'
            '    return (s32) __repair_out;\n')
    return [('measured_indirect_command_records', edit(source, [(part.opening + 1, part.end - 1, body)]))]

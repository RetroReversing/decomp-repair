"""Recover ordered pointer updates in an evidenced two-byte reader."""

import re

from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'lw \$a1, (?P<field>\d+)\(\$a0\)\naddiu \$v0, \$a1, 1\n'
    r'sw \$v0, (?P=field)\(\$a0\)\nlbu \$v0, \(\$a1\)\n'
    r'addiu \$v1, \$a1, 2\nsw \$v1, (?P=field)\(\$a0\)\n'
    r'lbu \$v1, 1\(\$a1\)\nsll \$v0, \$v0, 8\nor \$v0, \$v0, \$v1\n'
    r'sll \$v0, \$v0, 16\njr \$ra\nsra \$v0, \$v0, 16'
)
_SOURCE = _shape('''
    void *@pointer;
    @pointer = M2C_FIELD(@arg, void **, @field);
    M2C_FIELD(@arg, void **, @field) = (void *) (@pointer + 2);
    M2C_FIELD(@arg, void **, @field) = (void *) (@pointer + 1);
    return (s16) ((M2C_FIELD(@pointer, u8 *, 0) << 8) | M2C_FIELD(@pointer, u8 *, 1));
''', numbers=('field',))


def variants(source, name, header, rows):
    if len(rows) != 12:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    observed = _TARGET.fullmatch(target)
    changes = [normalized_integer_lines((left, right)) for marker, left, right in rows if marker != ' ']
    if (not observed or ('addiu $v1, $a1, 2', '') not in changes
            or (f'sw $v1, {observed["field"]}($a0)', '') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    sig = re.search(rf'\bs16 {re.escape(name)}\(void \*({IDENT})\)\s*$', part.clean[:part.opening])
    if (not draft or not sig or sig[1] != draft['arg'] or integer(draft['field']) != int(observed['field'])
            or draft['arg'] == draft['pointer']
            or re.search(r'\bvolatile\b|\b__repair_first\b|\b__repair_second\b', part.clean)):
        return []
    arg, pointer, field = draft['arg'], draft['pointer'], draft['field']
    ptrfield = f'M2C_FIELD({arg}, void **, {field})'
    body = (f'\n    void *{pointer};\n    s32 __repair_first;\n    s32 __repair_second;\n\n'
            f'    {pointer} = {ptrfield};\n    {ptrfield} = (void *) ({pointer} + 1);\n'
            f'    __repair_first = M2C_FIELD({pointer}, u8 *, 0);\n'
            f'    {ptrfield} = (void *) ({pointer} + 2);\n'
            f'    __repair_second = M2C_FIELD({pointer}, u8 *, 1);\n'
            '    return (s16) ((__repair_first << 8) | __repair_second);\n')
    fixed = edit(source, [(part.opening + 1, part.end - 1, body)])
    return [('measured_two_byte_reader_order', fixed)]

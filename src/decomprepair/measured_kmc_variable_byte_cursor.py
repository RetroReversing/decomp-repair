"""Recover a KMC input cursor for a one- or two-byte value."""

import re

from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'lbu \$a2, \(\$a1\)\nandi \$v0, \$a2, 128\nbeqz \$v0, 36\n'
    r'addiu \$a1, \$a1, 1\nlbu \$v1, \(\$a1\)\naddiu \$a1, \$a1, 1\n'
    r'andi \$v0, \$a2, 127\nsll \$v0, \$v0, 8\nor \$a2, \$v1, \$v0\n'
    r'sh \$a2, (?P<field>\d+)\(\$a0\)\njr \$ra\nmove \$v0, \$a1'
)
_SOURCE = _shape('''
    short @value; void *@cursor;
    @value = M2C_FIELD(@input, u8 *, 0);
    @cursor = @input + 1;
    if (@value & 0x80) {
        @cursor += 1;
        @value = M2C_FIELD(@input, u8 *, 1) | ((@value & 0x7F) << 8);
    }
    M2C_FIELD(@dest, s16 *, @field) = (s16) @value;
    return @cursor;
''', numbers=('field',))


def variants(source, name, header, rows):
    if len(rows) != 13:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    observed = _TARGET.fullmatch(target)
    changes = [normalized_integer_lines((left, right)) for tag, left, right in rows if tag != ' ']
    if (not observed or ('addiu $a1, $a1, 1', 'addiu $a3, $a1, 1') not in changes
            or ('addiu $a1, $a1, 1', '') not in changes):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    part.end = end
    draft = _SOURCE.fullmatch(' '.join(part.body.split()))
    if not draft or integer(draft['field']) != int(observed['field']):
        return []
    sig = re.search(rf'\bvoid \*{re.escape(name)}\(void \*({IDENT}), void \*({IDENT})\)\s*$',
                    part.clean[:part.opening])
    if (not sig or sig.groups() != (draft['dest'], draft['input'])
            or len(set(draft[key] for key in ('dest', 'input', 'cursor', 'value'))) != 4
            or re.search(r'\bvolatile\b', part.clean[part.opening:part.end])):
        return []
    dest, cursor, value = draft['dest'], draft['input'], draft['value']
    body = (f'\n    short {value};\n\n    {value} = *{cursor}++;\n'
            f'    if ({value} & 0x80) {{\n        {value} = *{cursor}++ | (({value} & 0x7F) << 8);\n    }}\n'
            f'    M2C_FIELD({dest}, s16 *, {draft["field"]}) = (s16) {value};\n    return {cursor};\n')
    second_type = sig.start(2) - len('void *')
    fixed = edit(source, [(second_type, second_type + len('void'), 'u8'),
                          (part.opening + 1, part.end - 1, body)])
    return [('measured_variable_byte_cursor', fixed)]

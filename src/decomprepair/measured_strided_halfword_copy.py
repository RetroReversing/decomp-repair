"""Restore a measured two-dimensional strided halfword copy."""

import re

from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines

BODY = _shape('''
    s32 @row;
    s32 @col;
    char *@dst;
    char *@src;
    @src = @arg;
    @dst = @callee(@global);
    @row = 0;
    if (M2C_FIELD(@global, s16 *, @height) > 0) {
        do {
            @col = 0;
            if (M2C_FIELD(@global, s16 *, @width) > 0) {
                @label: {
                    *(u16 *)@dst = *(u16 *)@src;
                    @src += 4;
                    @col += 1;
                    @dst += 2;
                }
                if (@col < M2C_FIELD(@global, s16 *, @width)) goto @label;
            }
            @row += 1;
            @src += @skip;
        } while (@row < M2C_FIELD(@global, s16 *, @height));
    }
''', numbers=('height', 'width', 'skip'))


def variants(source, name, header, rows):
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    if not re.search(r'lhu \$v0, \(\$s0\)\nsh \$v0, \(\$a1\)', target):
        return []
    if 'addiu $s0, $s0, 4' not in target or 'addiu $a1, $a1, 2' not in target:
        return []
    part = view(source, name)
    if not part:
        return []
    if any(mark in source[part.opening + 1:part.end - 1] for mark in ('/*', '//', '#')):
        return []
    m = BODY.fullmatch(' '.join(part.body.split()))
    if not m or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*u16\s*\*\s*{m["arg"]}\s*\)\s*$',
                              part.clean[:part.opening]):
        return []
    names = ('row', 'col', 'dst', 'src', 'arg', 'callee', 'global')
    if len({m[k] for k in names}) != len(names):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if macros.intersection(m[k] for k in names):
        return []
    skip = integer(m['skip'])
    if not 0 < skip <= 32767 or skip % 2 or f'addiu $s0, $s0, {skip}' not in target:
        return []
    for key in ('height', 'width'):
        off = integer(m[key])
        if not re.search(rf'\blh \$\w+, {off}\(\$\w+\)', target):
            return []
    if not re.search(rf'\bjal {re.escape(m["callee"])}\b', target):
        return []
    if not re.search(rf'\bu16\s*\*\s*{re.escape(m["callee"])}\s*\(', part.clean[:part.opening] + '\n' + header):
        return []
    if not re.search(rf'lui \$\w+, %hi\({re.escape(m["global"])}\)', target):
        return []
    body = f'''
    s32 {m['row']};
    s32 {m['col']};
    u16 *{m['dst']};
    {m['dst']} = {m['callee']}({m['global']});
    for ({m['row']} = 0; {m['row']} < M2C_FIELD({m['global']}, s16 *, {m['height']}); {m['row']}++) {{
        for ({m['col']} = 0; {m['col']} < M2C_FIELD({m['global']}, s16 *, {m['width']}); {m['col']}++) {{
            *{m['dst']}++ = *{m['arg']};
            {m['arg']} += 2;
        }}
        {m['arg']} += {skip // 2};
    }}
'''
    return [('measured_strided_halfword_copy', edit(source, [(part.opening + 1, part.end - 1, body)]))]

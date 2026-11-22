"""Restore a measured indexed loop over count and allocated-pointer arrays."""

import re

from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines

BODY = _shape('''
    u16 @count;
    u32 @index;
    void *@allocated;
    void *@base;
    void *@cursor;
    @base = (char *)&@state + @baseoff;
    @clear(@base, 0, @bytes);
    @index = 0;
    @parse(&@first, &@second);
    @cursor = @base;
    @label: {
        @count = M2C_FIELD(@base, u16 *, @countoff);
        if (@count != 0) {
            @allocated = @alloc(1, @count * @size);
            M2C_FIELD(@cursor, void **, @ptroff) = @allocated;
            @clear(@allocated, 0, M2C_FIELD(@base, u16 *, @countoff) * @size);
        }
        @cursor += 4;
        @index += 1;
        @base += 2;
    }
    if (@index < @limit) goto @label;
    @parse(&@first, &@third);
    M2C_FIELD(&@state, s32 *, @resetoff) = 0;
    @reset();
''', numbers=('baseoff', 'bytes', 'countoff', 'size', 'ptroff', 'limit', 'resetoff'))


def variants(source, name, header, rows):
    target, candidate = ('\n'.join(normalized_integer_lines(row[side] for row in rows if row[side]))
                         for side in (1, 2))
    if not re.search(r'lhu \$v0, \d+\(\$s0\)\nbeql \$v0, \$zero, \d+\naddiu \$s1, \$s1, 4', target):
        return []
    if not re.search(r'lhu \$v0, \d+\(\$s0\)\nbeqz \$v0, \d+', candidate):
        return []
    part = view(source, name)
    if not part or any(mark in source[part.opening + 1:part.end - 1] for mark in ('/*', '//', '#')):
        return []
    m = BODY.fullmatch(' '.join(part.body.split()))
    if not m or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\)\s*$', part.clean[:part.opening]):
        return []
    names = ('count', 'index', 'allocated', 'base', 'cursor', 'state', 'clear', 'parse', 'first',
             'second', 'third', 'alloc', 'reset')
    if len({m[k] for k in names}) != len(names):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if macros.intersection(m[k] for k in names):
        return []
    limit, countoff, ptroff = (integer(m[k]) for k in ('limit', 'countoff', 'ptroff'))
    if not 1 <= limit <= 64 or not 1 <= integer(m['size']) <= 65535:
        return []
    if not all((f'lhu $v0, {countoff}($s0)' in target,
                f'sw $v0, {ptroff}($s1)' in target,
                f'sltiu $v0, $s2, {limit}' in target,
                f'jal {m["alloc"]}' in target,
                f'jal {m["clear"]}' in target)):
        return []
    body = f'''
    u32 {m['index']};
    void *{m['base']};
    {m['base']} = (char *)&{m['state']} + {m['baseoff']};
    {m['clear']}({m['base']}, 0, {m['bytes']});
    {m['parse']}(&{m['first']}, &{m['second']});
    for ({m['index']} = 0; {m['index']} < {m['limit']}; {m['index']}++) {{
        if (M2C_FIELD(({m['base']} + {m['index']} * 2), u16 *, {m['countoff']}) != 0) {{
            M2C_FIELD(({m['base']} + {m['index']} * 4), void **, {m['ptroff']}) =
                {m['alloc']}(1, M2C_FIELD(({m['base']} + {m['index']} * 2), u16 *, {m['countoff']}) * {m['size']});
            {m['clear']}(M2C_FIELD(({m['base']} + {m['index']} * 4), void **, {m['ptroff']}), 0,
                M2C_FIELD(({m['base']} + {m['index']} * 2), u16 *, {m['countoff']}) * {m['size']});
        }}
    }}
    {m['parse']}(&{m['first']}, &{m['third']});
    M2C_FIELD(&{m['state']}, s32 *, {m['resetoff']}) = 0;
    {m['reset']}();
'''
    return [('measured_indexed_allocations', edit(source, [(part.opening + 1, part.end - 1, body)]))]

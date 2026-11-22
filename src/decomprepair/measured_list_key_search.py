"""Restore a measured null-terminated list search with a key comparison."""

import re

from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines

BODY = _shape('''
    void *@result;
    void *@cursor;
    @cursor = *M2C_FIELD(&@base, void ***, @head);
    @result = NULL;
    if (@cursor != NULL) {
        @label:
        @result = @cursor;
        if (M2C_FIELD(@cursor, s32 *, @key) != @arg) {
            @cursor = M2C_FIELD(@cursor, void **, @next);
            @result = NULL;
            if (@cursor != NULL) { goto @label; }
        }
    }
    return @result;
''', numbers=('head', 'key', 'next'))

TARGET = re.compile(
    rf'lui \$v0, %hi\((?P<head>{IDENT})\)\nlw \$v0, %lo\((?P=head)\)\(\$v0\)\n'
    rf'lw \$v1, \(\$v0\)\nbeqz \$v1, \d+\nmove \$v0, \$zero\n'
    rf'lw \$v0, (?P<key>\d+)\(\$v1\)\nbeq \$v0, \$a0, \d+\nmove \$v0, \$v1\n'
    rf'lw \$v1, (?P<next>\d+)\(\$v1\)\nbnez \$v1, \d+\nmove \$v0, \$zero\n'
    rf'jr \$ra\nnop'
)


def variants(source, name, header, rows, resolve):
    if not resolve:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    measured = TARGET.search(target)
    part = view(source, name)
    if not measured or not part:
        return []
    if any(mark in source[part.opening + 1:part.end - 1] for mark in ('/*', '//', '#')):
        return []
    m = BODY.fullmatch(' '.join(part.body.split()))
    if not m or not re.search(rf'\bvoid\s*\*\s*{re.escape(name)}\s*\(\s*s32\s+{m["arg"]}\s*\)\s*$',
                              part.clean[:part.opening]):
        return []
    names = ('result', 'cursor', 'base', 'arg')
    if len({m[k] for k in names}) != len(names):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if macros.intersection(m[k] for k in names):
        return []
    base = resolve(m['base'])
    if (base is None or resolve(measured['head']) != base + integer(m['head'])
            or integer(m['key']) != int(measured['key']) or integer(m['next']) != int(measured['next'])):
        return []
    body = f'''
    void *{m['cursor']};
    {m['cursor']} = *M2C_FIELD(&{m['base']}, void ***, {m['head']});
    while ({m['cursor']} != NULL) {{
        if (M2C_FIELD({m['cursor']}, s32 *, {m['key']}) == {m['arg']})
            return {m['cursor']};
        {m['cursor']} = M2C_FIELD({m['cursor']}, void **, {m['next']});
    }}
    return NULL;
'''
    return [('measured_list_key_search', edit(source, [(part.opening + 1, part.end - 1, body)]))]

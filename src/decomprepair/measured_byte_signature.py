"""Stage the bytes and constants of a measured three-byte signature check."""

import re

from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines

BODY = _shape('''
    s32 @result;
    @result = 0;
    if ((M2C_FIELD(&@base, u8 *, @offa) == @ca) && (M2C_FIELD(&@base, u8 *, @offb) == @cb)) {
        @result = M2C_FIELD(&@base, u8 *, @offc) == @cc;
    }
    return @result;
''', numbers=('offa', 'offb', 'offc', 'ca', 'cb', 'cc'))

TARGET = re.compile(
    rf'lui \$a0, %hi\((?P<a>{IDENT})\)\nlbu \$a0, %lo\((?P=a)\)\(\$a0\)\n'
    rf'addiu \$v1, \$zero, (?P<ca>\d+)\nbne \$a0, \$v1, \d+\nmove \$v0, \$zero\n'
    rf'lui \$a0, %hi\((?P<b>{IDENT})\)\nlbu \$a0, %lo\((?P=b)\)\(\$a0\)\n'
    rf'addiu \$v1, \$zero, (?P<cb>\d+)\nbne \$a0, \$v1, \d+\nnop\n'
    rf'lui \$v0, %hi\((?P<c>{IDENT})\)\nlbu \$v0, %lo\((?P=c)\)\(\$v0\)\n'
    rf'xori \$v0, \$v0, (?P<cc>\d+)\nsltiu \$v0, \$v0, 1\njr \$ra\nnop'
)


def variants(source, name, header, rows, resolve):
    if not resolve:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    measured = TARGET.search(target)
    part = view(source, name)
    if not measured or not part:
        return []
    original = source[part.opening + 1:part.end - 1]
    if any(mark in original for mark in ('/*', '//', '#')):
        return []
    m = BODY.fullmatch(' '.join(part.body.split()))
    if not m or not re.search(rf'\bs32\s+{re.escape(name)}\s*\(\s*void\s*\)\s*$', part.clean[:part.opening]):
        return []
    if m['base'] == m['result'] or re.search(r'\b__repair_(?:byte|expected)\b', part.clean + '\n' + header):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if macros.intersection((m['base'], m['result'])):
        return []
    base = resolve(m['base'])
    if base is None:
        return []
    for key in ('a', 'b', 'c'):
        if resolve(measured[key]) != base + integer(m['off' + key]) or integer(m['c' + key]) != int(measured['c' + key]):
            return []
        if not 0 <= integer(m['c' + key]) <= 255:
            return []
    body = f'''
    s32 __repair_expected;
    s32 __repair_byte;
    s32 {m['result']};
    __repair_byte = M2C_FIELD(&{m['base']}, u8 *, {m['offa']});
    __repair_expected = {m['ca']};
    {m['result']} = 0;
    if (__repair_byte == __repair_expected) {{
        __repair_byte = M2C_FIELD(&{m['base']}, u8 *, {m['offb']});
        __repair_expected = {m['cb']};
        if (__repair_byte == __repair_expected)
            {m['result']} = M2C_FIELD(&{m['base']}, u8 *, {m['offc']}) == {m['cc']};
    }}
    return {m['result']};
'''
    return [('measured_byte_signature', edit(source, [(part.opening + 1, part.end - 1, body)]))]

"""Restore measured bit-field staging and the low half of a stack argument."""

import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines

BODY = _shape('''
    s32 @high;
    s32 @bits;
    void *@cursor;
    @cursor = M2C_FIELD(@obj, void **, @offset);
    @high = (@a & 0x1F) << 0x11;
    @bits = (@c & 0x1F) * 2;
    ((@record*)@cursor)->field_0 = (s32) (@high | ((@b & 0x1F) << 9) | @bits | 0x07000000);
    ((@record*)@cursor)->field_4 = (s32) (@high | (@bits << 8) | ((@d & 0x1F) * 2));
    M2C_FIELD(@obj, void **, @offset) = (void *) (M2C_FIELD(@obj, void **, @offset) + 8);
''', numbers=('offset',))

TARGET = re.compile(
    r'andi \$a1, \$a1, 31\nsll \$a1, \$a1, 17\n'
    r'andi \$a2, \$a2, 31\nsll \$a2, \$a2, 9\nor \$a2, \$a1, \$a2\n'
    r'andi \$a3, \$a3, 31\nsll \$a3, \$a3, 1\nor \$a2, \$a2, \$a3\n'
    r'lui \$v0, 1792\nor \$a2, \$a2, \$v0\nsw \$a2, \(\$v1\)\n'
    r'lhu \$v0, 18\(\$sp\)\nsll \$a3, \$a3, 8\nor \$a1, \$a1, \$a3'
)


def variants(source, name, header, rows, flags, big_endian):
    flags = set(flags or ())
    if not big_endian or not flags.intersection({'-mgp32', '-mabi=32'}) or flags.intersection({'-mgp64', '-m64', '-mabi=64', '-mabi=n32', '-mabi=eabi'}):
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    if not TARGET.search(target):
        return []
    part = view(source, name)
    if not part or any(mark in source[part.opening + 1:part.end - 1] for mark in ('/*', '//', '#')):
        return []
    m = BODY.fullmatch(' '.join(part.body.split()))
    if not m:
        return []
    signature = re.search(
        rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\*\s*{m["obj"]}\s*,\s*s32\s+{m["a"]}\s*,'
        rf'\s*s32\s+{m["b"]}\s*,\s*s32\s+{m["c"]}\s*,\s*(?P<type>u16)\s+{m["d"]}\s*\)\s*$',
        part.clean[:part.opening],
    )
    if not signature:
        return []
    outside = part.clean[:signature.start()] + part.clean[part.end:] + '\n' + _blank(header)
    if re.search(rf'\b{re.escape(name)}\s*\(', outside):
        return []
    names = ('obj', 'a', 'b', 'c', 'd', 'high', 'bits', 'cursor', 'record')
    if len({m[k] for k in names}) != len(names) or re.search(r'\b__repair_(?:word|index)\b', part.clean + '\n' + header):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if macros.intersection(m[k] for k in names):
        return []
    offset = integer(m['offset'])
    if not re.search(rf'\blw \$v1, {offset}\(\$a0\)', target) or not re.search(rf'\bsw \$v1, {offset}\(\$a0\)', target):
        return []
    body = f'''
    s32 *{m['cursor']} = M2C_FIELD({m['obj']}, s32 **, {m['offset']});
    s32 {m['high']};
    s32 __repair_word;
    s32 {m['bits']};
    {m['high']} = ({m['a']} & 0x1F) << 17;
    __repair_word = {m['high']} | (({m['b']} & 0x1F) << 9);
    {m['bits']} = {m['c']} & 0x1F;
    {m['bits']} = {m['bits']} << 1;
    __repair_word = __repair_word | {m['bits']};
    {m['cursor']}[0] = __repair_word | 0x07000000;
    {m['bits']} = {m['bits']} << 8;
    {m['high']} |= {m['bits']};
    {m['high']} |= (((u16 *)&{m['d']})[1] & 0x1F) << 1;
    {m['cursor']}[1] = {m['high']};
    {m['cursor']} = (s32 *)((char *)M2C_FIELD({m['obj']}, void **, {m['offset']}) + 8);
    M2C_FIELD({m['obj']}, void **, {m['offset']}) = {m['cursor']};
'''
    return [('measured_packed_quad', edit(source, [(*signature.span('type'), 's32'),
                                                    (part.opening + 1, part.end - 1, body)]))]

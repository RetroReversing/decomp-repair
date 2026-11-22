"""Restore a measured byte-to-record ramp loop."""

import re

from .integer_repair_support import IDENT, edit, view

# This complete generated body excludes extra calls, writes and alternate paths.
_TEMPLATE = '''
s32 @masked@;
s32 @offset@;
s32 @step@;
s32 @counter@;
s32 @value@;
u16 @count@;
short @level@;
void *@table@;
@table@ = M2C_FIELD(@obj@, void **, @table_off@);
@count@ = M2C_FIELD(@obj@, u16 *, @count_off@);
@level@ = M2C_FIELD(@table@, u8 *, @start_off@);
@step@ = (s32) (M2C_FIELD(@table@, u8 *, @end_off@) - @level@) / (s32) (@count@ - 1);
@counter@ = 0;
if (@count@ != 0) {
    @value@ = @level@ * 5;
    @label@: {
        @masked@ = @counter@ & 0xFFFF;
        @offset@ = @masked@ * 0xC;
        @callee@(@obj@, @masked@, (s16) @level@, M2C_FIELD(M2C_FIELD(@obj@, void **, @table_off@), s32 *, @array_off@) + @offset@ + 6);
        @counter@ += 1;
        M2C_FIELD((@offset@ + M2C_FIELD(M2C_FIELD(@obj@, void **, @table_off@), s32 *, @array_off@)), s16 *, 4) = (s16) (@value@ * 2);
        @value@ += @step@ * 5;
        @level@ += @step@;
    }
    if ((u32) (@counter@ & 0xFFFF) < (u16) M2C_FIELD(@obj@, u16 *, @count_off@)) goto @label@;
}
'''


def _body_pattern():
    chunks = re.split(r'(@\w+@|\s+)', _TEMPLATE)
    seen = set()
    result = []
    for chunk in chunks:
        if chunk.isspace():
            result.append(r'\s*')
        elif chunk.startswith('@') and chunk.endswith('@'):
            key = chunk[1:-1]
            if key in seen:
                result.append(r'(?P=' + key + ')')
            else:
                seen.add(key)
                val = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)' if key.endswith('_off') else IDENT
                result.append(r'(?P<' + key + '>' + val + ')')
        else:
            result.append(re.escape(chunk))
    return re.compile(''.join(result))


BODY = _body_pattern()


def variants(source, name, header, rows):
    target = '\n'.join(' '.join(left.split()) for _, left, _ in rows if left)
    if not re.search(r'\bdiv \$zero, \$v1, \$v0\b', target) or 'mflo $s5' not in target:
        return []
    if not re.search(r'sll \$s0, \$a1, 1\naddu \$s0, \$s0, \$a1\nsll \$s0, \$s0, 2', target):
        return []
    part = view(source, name)
    if not part:
        return []
    original = source[part.opening + 1:part.end - 1]
    if any(mark in original for mark in ('/*', '//', '#')):
        return []
    m = BODY.fullmatch(part.body)
    if not m or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(\s*void\s*\*\s*{m["obj"]}\s*\)\s*$',
                              part.clean[:part.opening]):
        return []
    names = ('masked', 'offset', 'step', 'counter', 'value', 'count', 'level', 'table', 'obj', 'callee')
    if len({m[k] for k in names}) != len(names):
        return []
    macros = set(re.findall(r'(?m)^\s*#\s*define\s+(' + IDENT + r')\b', source + '\n' + header))
    if macros.intersection(m[k] for k in names):
        return []
    if re.search(r'\b__repair_(?:start|end)\b', part.clean + '\n' + header):
        return []
    for key in ('table_off', 'count_off', 'start_off', 'end_off', 'array_off'):
        off = int(m[key], 0)
        if not re.search(rf'\b(?:lw|lbu|lhu) \$\w+, (?:0x{off:x}|{off})\(\$\w+\)', target):
            return []
    if not re.search(rf'\bjal {re.escape(m["callee"])}\b', target):
        return []
    body = f'''
    s32 {m['masked']}, {m['step']}, {m['counter']}, {m['value']}, {m['level']};
    u8 __repair_start, __repair_end;
    void *{m['table']};
    {m['table']} = M2C_FIELD({m['obj']}, void **, {m['table_off']});
    {m['masked']} = M2C_FIELD({m['obj']}, u16 *, {m['count_off']});
    __repair_start = M2C_FIELD({m['table']}, u8 *, {m['start_off']});
    __repair_end = M2C_FIELD({m['table']}, u8 *, {m['end_off']});
    {m['step']} = (s32) (__repair_end - __repair_start) / (s32) ({m['masked']} - 1);
    {m['level']} = __repair_start;
    {m['counter']} = 0;
    if ({m['masked']} != 0) {{
        {m['value']} = {m['level']} * 5;
        {m['label']}:
        {m['masked']} = {m['counter']} & 0xFFFF;
        {m['callee']}({m['obj']}, {m['masked']}, (s16) {m['level']},
            M2C_FIELD(M2C_FIELD({m['obj']}, void **, {m['table_off']}), s32 *, {m['array_off']}) + {m['masked']} * 0xC + 6);
        {m['counter']} += 1;
        M2C_FIELD(({m['masked']} * 0xC + M2C_FIELD(M2C_FIELD({m['obj']}, void **, {m['table_off']}), s32 *, {m['array_off']})), s16 *, 4) = (s16) ({m['value']} * 2);
        {m['value']} += {m['step']} * 5;
        if ((u32) ({m['counter']} & 0xFFFF) < (u16) M2C_FIELD({m['obj']}, u16 *, {m['count_off']})) {{
            {m['level']} += {m['step']};
            goto {m['label']};
        }}
    }}
'''
    return [('measured_record_ramp', edit(source, [(part.opening + 1, part.end - 1, body)]))]

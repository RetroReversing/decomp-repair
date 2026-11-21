"""Recover typed byte cursors and word-sized formals in measured IDO drafts."""

import re

from .integer_repair_support import edit, view
from .large_stack_drafts import _shape
from .mips_returns import instructions
from .pattern_repairs import close

_WORD = _shape('''
    void *@original; void *@next;
    @original = *@cursor; @next = @original + 1;
    *@cursor = @next; *@cursor = @next + 1;
    return (s16) (M2C_FIELD(@original, u8 *, 1) | (s16) (M2C_FIELD(@original, u8 *, 0) << 8));
''')
_COMPRESSED = _shape('''
    u8 @value; void *@next; void *@original;
    @original = *@cursor; @value = M2C_FIELD(@original, u8 *, 0);
    @next = @original + 1; *@cursor = @next;
    if (@value & 0x80) {
        @value = (M2C_FIELD(@original, u8 *, 1) | ((@value << 8) & 0x7F00)) & 0xFFFF;
        *@cursor = @next + 1;
    }
    return @value;
''')
_BIASED = _shape('''
    s32 @index; u8 *@input; void *@next;
    M2C_FIELD(@out, s8 *, 0) = @first;
    M2C_FIELD(@out, s8 *, 1) = @second;
    @index = 0; @next = @out; @input = @bytes;
    do {
        @index += 1; @next += 1;
        M2C_FIELD(@next, s8 *, 1) = (s8) (*@input - 0x61);
        @input += 1;
    } while (@index != 3);
    M2C_FIELD(@out, s8 *, 5) = (s8) @lastfirst;
    M2C_FIELD(@out, s8 *, 6) = (s8) @lastsecond;
    M2C_FIELD(@out, s8 *, 7) = (s8) @lastthird;
''')

# These instruction sequences distinguish a signed halfword, a variable-width
# integer, and three biased bytes. The memory order and delay slots matter.
_WORD_ASM = '''
lw $a1, 0($a0)
lbu $v1, 0($a1)
addiu $t6, $a1, 1
sw $t6, 0($a0)
lbu $t7, 0($t6)
sll $v1, $v1, 8
sll $v1, $v1, 16
sra $v1, $v1, 16
or $v1, $t7, $v1
sll $v1, $v1, 16
addiu $t8, $t6, 1
sw $t8, 0($a0)
jr $ra
sra $v0, $v1, 16
'''.strip()
_COMPRESSED_ASM = '''
lw $v0, 0($a0)
lbu $v1, 0($v0)
addiu $t6, $v0, 1
sw $t6, 0($a0)
andi $t7, $v1, 128
beqz $t7, .Lexit
move $a1, $v1
lbu $t8, 0($t6)
sll $v1, $a1, 8
andi $v1, $v1, 32512
addiu $t9, $t6, 1
or $v1, $t8, $v1
andi $v1, $v1, 65535
sw $t9, 0($a0)
jr $ra
move $v0, $v1
'''.strip()
_BIASED_ASM = '''
sb $a1, 0($a0)
sb $a2, 1($a0)
addiu $a1, $zero, 3
move $v0, $zero
move $v1, $a0
move $t0, $a3
lbu $t6, 0($t0)
addiu $v0, $v0, 1
addiu $v1, $v1, 1
addiu $t7, $t6, -97
sb $t7, 1($v1)
bne $v0, $a1, .Lloop
addiu $t0, $t0, 1
lw $t8, 16($sp)
sb $t8, 5($a0)
lw $t9, 20($sp)
sb $t9, 6($a0)
lw $t1, 24($sp)
jr $ra
sb $t1, 7($a0)
'''.strip()
_SHAPES = {
    _WORD_ASM: (_WORD, 'initial_ido_word_cursor'),
    _COMPRESSED_ASM: (_COMPRESSED, 'initial_ido_variable_word_cursor'),
    _BIASED_ASM: (_BIASED, 'initial_ido_biased_byte_copy'),
}


def variants(source, name, asm, header=''):
    if (not asm or 'M2C_FIELD(' not in source or ('void **' not in source and 's8 *' not in source)
            or re.search(rf'\b{re.escape(name)}\s*\(', header)):
        return []
    ops = [' '.join(row.split()) for row in instructions(asm)]
    branch = {16: (14, '.Lexit'), 20: (6, '.Lloop')}.get(len(ops))
    if branch:
        labels = re.findall(r'(?m)^\s*(\.L\w+):\s*$', asm)
        if len(labels) != 1:
            return []
        # Require the whole body shape and the branch to the correct instruction.
        following = asm.split(labels[0] + ':', 1)[1]
        index, canonical = branch
        if len(ops) - len(instructions(following)) != index:
            return []
        ops = [row.replace(labels[0], canonical) for row in ops]
    text = '\n'.join(ops)
    text = re.sub(r'(?<!\w)-?0x[\da-fA-F]+\b', lambda m: str(int(m[0], 16)), text)
    text = re.sub(r'(?m)^(?:or|addu) (\$\w+), (\$\w+), \$zero$', r'move \1, \2', text)
    selected = _SHAPES.get(text)
    if not selected or not (part := view(source, name)):
        return []
    shape, family = selected
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    match = shape.fullmatch(' '.join(part.clean[part.opening + 1:end - 1].split()))
    if not match or len(set(match.groupdict().values())) != len(match.groupdict()):
        return []
    if shape is _BIASED:
        candidate = _biased(part, name, match, end)
    else:
        candidate = _cursor(part, name, header, match['cursor'], end, compressed=shape is _COMPRESSED)
    return [(family, candidate)] if candidate else []


def _cursor(part, name, header, cursor, end, *, compressed):
    before = 'u8' if compressed else 's16'
    signature = re.search(rf'\b(?P<return>{before})\s+{re.escape(name)}\(\s*(?P<type>void\s*\*\s*\*)'
                          rf'\s*{cursor}\s*\)\s*$', part.clean[:part.opening])
    if not signature:
        return None
    if compressed:
        # IDO coalesces the shifted temporary differently without these
        # unreachable source statements at the two allocation boundaries.
        body = f"""
    u8 *__repair_input = *{cursor};
    s32 __repair_value = *__repair_input;
    s32 __repair_original = __repair_value;
    *{cursor} = __repair_input + 1;
    if (__repair_value & 0x80) {{
        __repair_value = __repair_original << 8;
        while (0) {{ __repair_value += 1; }}
        __repair_value &= 0x7F00;
        while (0) {{ __repair_value += 1; }}
        __repair_value = **{cursor} | __repair_value;
        __repair_value &= 0xFFFF;
        (*{cursor})++;
    }}
    return __repair_value;
"""
    else:
        body = f"""
    s16 __repair_value = *(*{cursor})++ << 8;
    __repair_value = *(*{cursor})++ | __repair_value;
    return __repair_value;
"""
    if re.search(r'\b__repair_(?:input|value|original)\b', part.clean + header):
        return None
    edits = [(*signature.span('type'), 'u8 **'), (part.opening + 1, end - 1, body)]
    if compressed:
        edits.append((*signature.span('return'), 's32'))
    return edit(part.source, edits)


def _biased(part, name, match, end):
    out, first, second, data, last_first, last_second, last_third = (match[k] for k in
        ('out', 'first', 'second', 'bytes', 'lastfirst', 'lastsecond', 'lastthird'))
    signature = re.search(
        rf'\bvoid\s+{re.escape(name)}\((?P<params>\s*void\s*\*\s*{out}\s*,\s*s8\s+{first}\s*,\s*s8\s+{second}\s*,'
        rf'\s*u8\s*\*\s*{data}\s*,\s*s32\s+{last_first}\s*,\s*s32\s+{last_second}\s*,\s*s32\s+{last_third}\s*)\)\s*$',
        part.clean[:part.opening])
    if not signature:
        return None
    index, pointer, input_ = match['index'], match['next'], match['input']
    declaration = f's8 *{out}, s32 {first}, s32 {second}, u8 *{data}, s32 {last_first}, s32 {last_second}, s32 {last_third}'
    body = f"""
    s32 {index};
    s8 *{pointer};
    u8 *{input_};
    {out}[0] = {first};
    {out}[1] = {second};
    for ({index} = 0, {pointer} = {out}, {input_} = {data}; {index} < 3;) {{
        {index}++;
        {pointer}++;
        {pointer}[1] = *{input_} - 0x61;
        {input_}++;
    }}
    {out}[5] = {last_first};
    {out}[6] = {last_second};
    {out}[7] = {last_third};
"""
    return edit(part.source, [(*signature.span('params'), declaration), (part.opening + 1, end - 1, body)])

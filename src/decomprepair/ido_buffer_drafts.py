"""Restore IDO's typed record indexing and the loops it unrolled."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close
from .shared_default_drafts import _instructions

_QUEUE = _shape('''
    s32 @next; s32 @state; s32 @ready;
    @state = M2C_FIELD(@base, s32 *, 0x54);
    if (@state != 0) { if (@state == 1) {
    @ready = M2C_FIELD(@base, s32 *, 0x58);
    if (@ready >= M2C_FIELD(@base, s32 *, 0x4C)) {
    M2C_FIELD(@base, s32 *, 0x4C) = @ready;
    M2C_FIELD(@base, s32 *, 0x48) = 0;
    M2C_FIELD(@base, s32 *, 0x40) = (s32) M2C_FIELD(@base, s32 *, 0x44);
    goto @join; } } } else { @join:
    *(@base + (M2C_FIELD(@base, s32 *, 0x40) * 4)) = M2C_FIELD(@base, s32 *, 0x5C);
    @next = M2C_FIELD(@base, s32 *, 0x40) + 1;
    M2C_FIELD(@base, s32 *, 0x40) = @next;
    M2C_FIELD(@base, s32 *, 0x40) = (s32) (@next & 0xF); }
    M2C_FIELD(@base, s32 *, 0x5C) = 0;
''')
_FLOAT = _shape('''
    s32 @count; void *@ps; void *@ss; void *@pd; void *@dd; void *@from; void *@to;
    @from = @src; @to = @dst; @count = 0;
    do { @ps = @from + 4;
    M2C_FIELD(@to, f32 *, 0) = (f32) M2C_FIELD(@from, f32 *, 0);
    @pd = @to + 4; @ss = @ps + 4;
    M2C_FIELD(@to, f32 *, 4) = (f32) M2C_FIELD(@from, f32 *, 4);
    @dd = @pd + 4;
    M2C_FIELD(@pd, f32 *, 4) = (f32) M2C_FIELD(@ps, f32 *, 4);
    @count += 4; @to = @dd + 4 + 4; @from = @ss + 4 + 4;
    M2C_FIELD(@dd, f32 *, 4) = (f32) M2C_FIELD(@ss, f32 *, 4); } while (@count != 0x10);
''')
_WORDS = _shape('''
    s32 *@srcone; s32 *@srcfour; s32 @remainder; s32 @scalar; s32 @first; s32 @bytes; s32 @pos;
    s32 @index; void *@dstone; void *@dstfour;
    M2C_FIELD(@base, s32 *, 0x1C) = @tag; M2C_FIELD(@base, s8 *, 4) = @count;
    @index = 0; if (@count > 0) {
    @remainder = @count & 3; if (@remainder != 0) {
    @bytes = 0 * 4; @dstone = @base + @bytes; @srcone = @src + @bytes;
    do { @scalar = *@srcone; @index += 1; @dstone += 4; @srcone += 4;
    M2C_FIELD(@dstone, s32 *, 4) = @scalar; } while (@remainder != @index);
    if (@index != @count) { goto @loop; } } else { @loop:
    @pos = @index * 4; @dstfour = @base + @pos; @srcfour = @src + @pos;
    do { @first = *@srcfour; @srcfour += 0x10; @dstfour += 0x10;
    M2C_FIELD(@dstfour, s32 *, -8) = @first;
    M2C_FIELD(@dstfour, s32 *, -4) = (s32) M2C_FIELD(@srcfour, s32 *, -0xC);
    M2C_FIELD(@dstfour, s32 *, 0) = (s32) M2C_FIELD(@srcfour, s32 *, -8);
    M2C_FIELD(@dstfour, s32 *, 4) = (s32) M2C_FIELD(@srcfour, s32 *, -4);
    } while (@srcfour != ((@count * 4) + @src)); } }
    M2C_FIELD(@base, s32 *, 0) = (s32) (M2C_FIELD(@base, s32 *, 0) | 0x80);
''')
_CHECKSUM = _shape('''
    s32 *@cursor; s32 @tail; s32 @length; s32 @last; s32 @one; s32 @chunk; s32 @value;
    s32 @total; s32 @index; void *@ptr; void *@third;
    @cursor = @src; @total = 0; @index = 0; @length = @count / 4;
    if (@length > 0) { @tail = @length & 3; if (@tail != 0) {
    do { @one = *@cursor; @index += 1; @cursor += 4; @total += @one; } while (@tail != @index);
    if (@index != @length) { goto @loop; } } else { do { @loop:
    @ptr = @cursor + 4; @third = @ptr + 4; @last = M2C_FIELD(@third, s32 *, 4); @index += 4;
    @chunk = @total + M2C_FIELD(@cursor, s32 *, 0) + M2C_FIELD(@cursor, s32 *, 4) + M2C_FIELD(@ptr, s32 *, 4);
    @cursor = @third + 4 + 4; @total = @chunk + @last; } while (@index != @length); } }
    @value = 0xF251F205 - @total; M2C_FIELD(@out, s32 *, 0) = @value;
    M2C_FIELD(@out, s32 *, 4) = (s32) (@key - (@value - @total));
''')

# Labels use instruction ordinals so the schedule is independent of the ROM address.
_TARGETS = {
    '''lw $v0, 84($a0)
addiu $at, $zero, 1
beql $v0, $zero, @16
lw $t9, 64($a0)
bne $v0, $at, @25
nop
lw $v0, 88($a0)
lw $t6, 76($a0)
slt $at, $v0, $t6
bnez $at, @25
nop
lw $t7, 68($a0)
sw $v0, 76($a0)
sw $zero, 72($a0)
sw $t7, 64($a0)
lw $t9, 64($a0)
lw $t8, 92($a0)
sll $t0, $t9, 2
addu $t1, $a0, $t0
sw $t8, 0($t1)
lw $t2, 64($a0)
addiu $t3, $t2, 1
sw $t3, 64($a0)
andi $t5, $t3, 15
sw $t5, 64($a0)
jr $ra
sw $zero, 92($a0)''': ('ido_word_queue', _QUEUE, rf'void \*({IDENT})', ('base',)),
    '''or $v0, $a0, $zero
or $v1, $a1, $zero
or $a2, $zero, $zero
addiu $a3, $zero, 16
or $a1, $v0, $zero
lwc1 $ft0, 0($a1)
addiu $v0, $v0, 4
or $a0, $v1, $zero
or $a1, $v0, $zero
swc1 $ft0, 0($a0)
lwc1 $ft1, 0($a1)
addiu $v1, $v1, 4
or $a0, $v1, $zero
addiu $v0, $v0, 4
or $a1, $v0, $zero
swc1 $ft1, 0($a0)
lwc1 $ft2, 0($a1)
addiu $v1, $v1, 4
or $a0, $v1, $zero
addiu $v0, $v0, 4
or $a1, $v0, $zero
swc1 $ft2, 0($a0)
lwc1 $ft3, 0($a1)
addiu $v1, $v1, 4
or $a0, $v1, $zero
addiu $a2, $a2, 4
addiu $v1, $v1, 4
addiu $v0, $v0, 4
bne $a2, $a3, @4
swc1 $ft3, 0($a0)
jr $ra
nop''': ('ido_linear_float_copy', _FLOAT, rf'void \*({IDENT}), void \*({IDENT})', ('src', 'dst')),
    '''sw $a1, 28($a0)
sb $a3, 4($a0)
blez $a3, @33
or $v0, $zero, $zero
andi $t2, $a3, 3
beqz $t2, @17
or $t1, $t2, $zero
sll $v1, $zero, 2
addu $a1, $a0, $v1
addu $t0, $a2, $v1
lw $t6, 0($t0)
addiu $v0, $v0, 1
addiu $a1, $a1, 4
addiu $t0, $t0, 4
bne $t1, $v0, @10
sw $t6, 4($a1)
beq $v0, $a3, @33
sll $v1, $v0, 2
sll $t7, $a3, 2
addu $t1, $t7, $a2
addu $a1, $a0, $v1
addu $t0, $a2, $v1
lw $t8, 0($t0)
addiu $t0, $t0, 16
addiu $a1, $a1, 16
sw $t8, -8($a1)
lw $t9, -12($t0)
sw $t9, -4($a1)
lw $t3, -8($t0)
sw $t3, 0($a1)
lw $t4, -4($t0)
bne $t0, $t1, @22
sw $t4, 4($a1)
lw $t5, 0($a0)
ori $t6, $t5, 128
jr $ra
sw $t6, 0($a0)''': ('ido_tagged_word_copy', _WORDS, rf'void \*({IDENT}), s32 ({IDENT}), s32 ({IDENT}), s8 ({IDENT})',
                       ('base', 'tag', 'src', 'count')),
    '''sw $a0, 0($sp)
or $v0, $zero, $zero
or $v1, $zero, $zero
bgez $a2, @7
sra $t0, $a2, 2
addiu $at, $a2, 3
sra $t0, $at, 2
blez $t0, @37
lui $t2, (4065456645 >> 16)
andi $a0, $t0, 3
beqz $a0, @19
or $a2, $a0, $zero
or $a0, $a1, $zero
lw $t6, 0($a0)
addiu $v1, $v1, 1
addiu $a1, $a1, 4
bne $a2, $v1, @12
addu $v0, $v0, $t6
beq $v1, $t0, @37
or $a0, $a1, $zero
lw $t7, 0($a0)
addiu $a1, $a1, 4
or $a0, $a1, $zero
lw $t8, 0($a0)
addiu $a1, $a1, 4
or $a0, $a1, $zero
lw $t9, 0($a0)
addiu $a1, $a1, 4
or $a0, $a1, $zero
addu $v0, $v0, $t7
lw $t1, 0($a0)
addu $v0, $v0, $t8
addiu $v1, $v1, 4
addu $v0, $v0, $t9
addiu $a1, $a1, 4
bne $v1, $t0, @19
addu $v0, $v0, $t1
lw $t3, 0($sp)
ori $t2, $t2, (4065456645 & 65535)
subu $v1, $t2, $v0
sw $v1, 0($t3)
lw $t5, 0($sp)
subu $v0, $v1, $v0
subu $t4, $a3, $v0
jr $ra
sw $t4, 4($t5)''': ('ido_word_checksum', _CHECKSUM, rf'void \*({IDENT}), s32 \*({IDENT}), s32 ({IDENT}), s32 ({IDENT})',
                     ('out', 'src', 'count', 'key')),
}


def _target(asm):
    if not asm or not any(op in asm for op in ('beql', 'bne', 'bgez')):
        return None
    lines, labels = _instructions(asm)
    if len(lines) not in (27, 32, 37, 46):
        return None
    rows = []
    for row in normalized_integer_lines(lines):
        if row.startswith(('beq ', 'beqz ', 'beql ', 'bne ', 'bnez ', 'blez ', 'bgez ')):
            op, _, label = row.rpartition(', ')
            if label not in labels:
                return None
            row = f'{op}, @{labels[label]}'
        rows.append(row)
    return _TARGETS.get('\n'.join(rows))


def applies(asm):
    return _target(asm) is not None


def variants(source, name, asm, header=''):
    if not source or 'M2C_FIELD(' not in source or '_m2c_buffer_' in source + header or not (target := _target(asm)):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    family, pattern, parameters, roles = target
    sig = re.search(rf'\bvoid\s+{re.escape(name)}\({parameters}\)\s*$', part.clean[:part.opening])
    if not sig or re.search(rf'\b{re.escape(name)}\s*\(', header + part.clean[:sig.start()]):
        return []
    draft = pattern.fullmatch(' '.join(part.clean[part.opening + 1:end - 1].split()))
    if not draft or tuple(draft[role] for role in roles) != sig.groups():
        return []
    emitter = _EMITTERS[family]
    return [(family, edit(source, [(sig.start(), end, emitter(name, *sig.groups()))]))]


def _queue(name, base):
    return f'''void {name}(s32 *{base}) {{
    s32 _m2c_buffer_state = {base}[0x54 / 4];
    if (_m2c_buffer_state != 0) {{
        if (_m2c_buffer_state != 1) goto _m2c_buffer_done;
        if ({base}[0x58 / 4] < {base}[0x4C / 4]) goto _m2c_buffer_done;
        {base}[0x4C / 4] = {base}[0x58 / 4];
        {base}[0x48 / 4] = 0;
        {base}[0x40 / 4] = {base}[0x44 / 4];
    }}
    {base}[{base}[0x40 / 4]] = {base}[0x5C / 4];
    {base}[0x40 / 4] = {base}[0x40 / 4] + 1;
    {base}[0x40 / 4] = {base}[0x40 / 4] & 15;
_m2c_buffer_done:
    {base}[0x5C / 4] = 0;
}}'''


def _floats(name, src, dst):
    copy = '''        _m2c_buffer_q = _m2c_buffer_out; _m2c_buffer_p = _m2c_buffer_in; _m2c_buffer_in++; _m2c_buffer_out++; *_m2c_buffer_q = *_m2c_buffer_p; _m2c_buffer_i++;
'''
    return f'''void {name}(f32 *{src}, f32 *{dst}) {{
    f32 *_m2c_buffer_in, *_m2c_buffer_out, *_m2c_buffer_p, *_m2c_buffer_q;
    s32 _m2c_buffer_i;
    _m2c_buffer_in = {src};
    _m2c_buffer_out = {dst};
    for (_m2c_buffer_i = 0; _m2c_buffer_i != 16;) {{
{copy * 4}    }}
}}'''


def _words(name, base, tag, src, count):
    return f'''void {name}(s8 *{base}, s32 {tag}, s32 {src}, s32 {count}) {{
    s32 _m2c_buffer_i;
    *(s32 *)({base} + 0x1C) = {tag};
    {base}[4] = {count};
    for (_m2c_buffer_i = 0; _m2c_buffer_i < {count}; _m2c_buffer_i++) {{
        ((s32 *)({base} + 8))[_m2c_buffer_i] = ((s32 *){src})[_m2c_buffer_i];
    }}
    *(s32 *){base} = *(s32 *){base} | 128;
}}'''


def _checksum(name, out, src, count, key):
    return f'''void {name}(s32 *{out}, s32 *{src}, s32 {count}, s32 {key}) {{
    s32 _m2c_buffer_sum = 0;
    s32 _m2c_buffer_i = 0;
    s32 *_m2c_buffer_p;
    s32 _m2c_buffer_value;
    if ({count} / 4 > 0) {{
        do {{
            _m2c_buffer_p = {src};
            {src}++;
            _m2c_buffer_i++;
            _m2c_buffer_sum += *_m2c_buffer_p;
        }} while (_m2c_buffer_i != {count} / 4);
    }}
    _m2c_buffer_value = 0xF251F205 - _m2c_buffer_sum;
    {out}[0] = _m2c_buffer_value;
    _m2c_buffer_sum = _m2c_buffer_value - _m2c_buffer_sum;
    {out}[1] = {key} - _m2c_buffer_sum;
}}'''


_EMITTERS = {
    'ido_word_queue': _queue,
    'ido_linear_float_copy': _floats,
    'ido_tagged_word_copy': _words,
    'ido_word_checksum': _checksum,
}

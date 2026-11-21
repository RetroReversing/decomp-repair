"""Recover IDO typed loop cursors when m2c infers raw void pointers."""

import re

from .integer_repair_support import IDENT, edit, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close
from .shared_default_drafts import _instructions

_RECIPROCAL = _shape('''
    f32 *@src; f32 @value; s32 @index; void *@dst;
    @src = @source; @index = 0; @dst = @destination;
    do { @index += 1; @dst += 0x10; @value = 1.0f / *@src; @src += 0x10;
    M2C_FIELD(@dst, f32 *, -0x10) = @value;
    M2C_FIELD(@dst, f32 *, -0xC) = (f32) (1.0f / M2C_FIELD(@src, f32 *, -0xC));
    M2C_FIELD(@dst, f32 *, -8) = (f32) (1.0f / M2C_FIELD(@src, f32 *, -8));
    M2C_FIELD(@dst, f32 *, -4) = (f32) (1.0f / M2C_FIELD(@src, f32 *, -4)); } while (@index != 4);
''')
_VISITOR = _shape('''
    s32 @index; void **@object; void *@table; void *@cursor;
    @index = 0; @cursor = @base;
    if (M2C_FIELD(@base, s32 *, 0x120) > 0) {
    do { @object = M2C_FIELD(@cursor, void ***, 0x134); @table = *@object;
    M2C_FIELD(@table, M2C_UNK (**)(void *), 0xC)(M2C_FIELD(@table, s16 *, 8) + @object);
    @index += 1; @cursor += 4; } while (@index < M2C_FIELD(@base, s32 *, 0x120)); }
''')
_RECORD = _shape('''
    s32 @scale; s32 @index; u8 *@read; void *@dstoff; void *@srcoff; void *@write;
    M2C_FIELD(@dst, s32 *, 0) = (s32) (@tag & 0xFF);
    @index = 0; @write = @dst; @read = @text;
    do { @index += 1; @write += 1; M2C_FIELD(@write, s8 *, 4) = (s8) (*@read - 0x61); @read += 1; }
    while (@index != 3);
    @scale = 1 * 4; @srcoff = @src + @scale;
    M2C_FIELD(@dst, s32 *, 8) = (s32) M2C_FIELD(@src, s32 *, 4);
    @dstoff = @dst + @scale;
    M2C_FIELD(@dstoff, s32 *, 8) = (s32) M2C_FIELD(@srcoff, s32 *, 4);
    M2C_FIELD(@dstoff, s32 *, 0xC) = (s32) M2C_FIELD(@srcoff, s32 *, 8);
    M2C_FIELD(@dstoff, s32 *, 0x10) = (s32) M2C_FIELD(@srcoff, s32 *, 0xC);
    M2C_FIELD(@dstoff, s32 *, 0x14) = (s32) M2C_FIELD(@srcoff, s32 *, 0x10);
    M2C_FIELD(@dst, s8 *, 4) = 5; M2C_FIELD(@dst, s32 *, 0x1C) = (s32) M2C_FIELD(@src, s32 *, 0);
''')
_TARGETS = {
    '''lui $at, (1065353216 >> 16)
or $a2, $a0, $zero
mtc1 $at, $fv0
addiu $a0, $zero, 4
or $v0, $zero, $zero
or $v1, $a1, $zero
lwc1 $ft0, 0($a2)
addiu $v0, $v0, 1
addiu $v1, $v1, 16
div.s $ft1, $fv0, $ft0
addiu $a2, $a2, 16
swc1 $ft1, -16($v1)
lwc1 $ft2, -12($a2)
div.s $ft3, $fv0, $ft2
swc1 $ft3, -12($v1)
lwc1 $ft4, -8($a2)
div.s $ft5, $fv0, $ft4
swc1 $ft5, -8($v1)
lwc1 $ft0, -4($a2)
div.s $ft1, $fv0, $ft0
bne $v0, $a0, @6
swc1 $ft1, -4($v1)
jr $ra
nop''': ('ido_reciprocal_matrix', _RECIPROCAL, rf'f32 \*({IDENT}), void \*({IDENT})', ('source', 'destination')),
    '''addiu $sp, $sp, -40
sw $ra, 36($sp)
sw $s2, 32($sp)
sw $s1, 28($sp)
sw $s0, 24($sp)
lw $t6, 288($a0)
or $s2, $a0, $zero
or $s0, $zero, $zero
blez $t6, @22
or $s1, $a0, $zero
lw $v1, 308($s1)
lw $v0, 0($v1)
lw $t9, 12($v0)
lh $t7, 8($v0)
jalr $t9
addu $a0, $t7, $v1
lw $t8, 288($s2)
addiu $s0, $s0, 1
addiu $s1, $s1, 4
slt $at, $s0, $t8
bnel $at, $zero, @11
lw $v1, 308($s1)
lw $ra, 36($sp)
lw $s0, 24($sp)
lw $s1, 28($sp)
lw $s2, 32($sp)
jr $ra
addiu $sp, $sp, 40''': ('ido_typed_virtual_visitor', _VISITOR, rf'void \*({IDENT})', ('base',)),
    '''andi $t6, $a1, 255
sw $t6, 0($a0)
addiu $a1, $zero, 3
or $v0, $zero, $zero
or $v1, $a0, $zero
or $t0, $a2, $zero
lbu $t7, 0($t0)
addiu $v0, $v0, 1
addiu $v1, $v1, 1
addiu $t8, $t7, -97
sb $t8, 4($v1)
bne $v0, $a1, @6
addiu $t0, $t0, 1
lw $t9, 4($a3)
addiu $v0, $zero, 1
sll $v1, $v0, 2
addu $a2, $a3, $v1
sw $t9, 8($a0)
lw $t1, 4($a2)
addu $a1, $a0, $v1
addiu $t5, $zero, 5
sw $t1, 8($a1)
lw $t2, 8($a2)
sw $t2, 12($a1)
lw $t3, 12($a2)
sw $t3, 16($a1)
lw $t4, 16($a2)
sw $t4, 20($a1)
sb $t5, 4($a0)
lw $t6, 0($a3)
jr $ra
sw $t6, 28($a0)''': ('ido_typed_record_copy', _RECORD, rf'void \*({IDENT}), s32 ({IDENT}), u8 \*({IDENT}), void \*({IDENT})',
                       ('dst', 'tag', 'text', 'src')),
}


def _target(asm):
    if not asm or 'addiu' not in asm or not any(op in asm for op in ('bnel', 'div.s', 'lbu')):
        return None
    lines, labels = _instructions(asm)
    if len(lines) not in (24, 28, 32):
        return None
    rows = []
    for row in normalized_integer_lines(lines):
        if row.startswith(('bne ', 'bnel ', 'blez ')):
            op, _, label = row.rpartition(', ')
            if label not in labels:
                return None
            row = f'{op}, @{labels[label]}'
        rows.append(row)
    return _TARGETS.get('\n'.join(rows))


def applies(asm):
    return _target(asm) is not None


def variants(source, name, asm, header=''):
    if not source or 'M2C_FIELD(' not in source or '_m2c_typed_' in source + header or not (target := _target(asm)):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end:
        return []
    family, pattern, parameters, roles = target
    signature = re.search(rf'\bvoid\s+{re.escape(name)}\({parameters}\)\s*$', part.clean[:part.opening])
    if not signature or re.search(rf'\b{re.escape(name)}\s*\(', header + part.clean[:signature.start()]):
        return []
    draft = pattern.fullmatch(' '.join(part.clean[part.opening + 1:end - 1].split()))
    if not draft or tuple(draft[role] for role in roles) != signature.groups():
        return []
    if family == 'ido_reciprocal_matrix':
        body = _reciprocal(name, *signature.groups())
    elif family == 'ido_typed_virtual_visitor':
        body = _visitor(name, *signature.groups())
    else:
        body = _record(name, *signature.groups())
    return [(family, edit(source, [(signature.start(), end, body)]))]


def _reciprocal(name, src, dst):
    return f'''void {name}(f32 *{src}, f32 *{dst}) {{
    int _m2c_typed_row, _m2c_typed_col;
    f32 *_m2c_typed_out, *_m2c_typed_in;

    for (_m2c_typed_row = 0, _m2c_typed_out = {dst}, _m2c_typed_in = {src}; _m2c_typed_row < 4; _m2c_typed_row++) {{
        for (_m2c_typed_col = 0; _m2c_typed_col < 4; _m2c_typed_col++) {{
            *_m2c_typed_out++ = 1.0f / (*_m2c_typed_in++);
        }}
    }}
}}'''


def _visitor(name, base):
    return f'''void {name}(s32 *{base}) {{
    s32 *_m2c_typed_cursor;
    s32 _m2c_typed_index;
    s32 _m2c_typed_offset;

    _m2c_typed_index = 0;
    _m2c_typed_cursor = {base};
    _m2c_typed_offset = 0x134;
    for (; _m2c_typed_index < {base}[0x120 / 4]; _m2c_typed_index++) {{
        s32 *_m2c_typed_object = (s32 *)_m2c_typed_cursor[_m2c_typed_offset / 4];
        s32 *_m2c_typed_table = (s32 *)((s32 *)_m2c_typed_cursor[_m2c_typed_offset / 4])[0];
        ((void (*)(s32))_m2c_typed_table[0xC / 4])(*((s16 *)((u8 *)_m2c_typed_table + 8)) + (s32)_m2c_typed_object);
        _m2c_typed_cursor++;
    }}
}}'''


def _record(name, dst, tag, text, src):
    return f'''void {name}(s32 *{dst}, s32 {tag}, u8 *{text}, s32 *{src}) {{
    s32 _m2c_typed_count;
    s8 *_m2c_typed_out;
    u8 *_m2c_typed_in;
    s32 _m2c_typed_word;

    *{dst} = {tag} & 0xFF;
    for (_m2c_typed_count = 0, _m2c_typed_out = (s8 *){dst}, _m2c_typed_in = {text}; ;) {{
        _m2c_typed_count++;
        _m2c_typed_out++;
        _m2c_typed_out[4] = *_m2c_typed_in - 0x61;
        _m2c_typed_in++;
        if (_m2c_typed_count == 3) break;
    }}
    for (_m2c_typed_word = 0; _m2c_typed_word < 5; _m2c_typed_word++) {{
        {dst}[_m2c_typed_word + 2] = {src}[_m2c_typed_word + 1];
    }}
    *((s8 *){dst} + 4) = 5;
    {dst}[7] = {src}[0];
}}'''

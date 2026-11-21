import pytest

from decomprepair.measured_kmc_carriers import variants


def rows(code, changes):
    result = [(' ' if line not in changes else 'r', line, changes.get(line, line))
              for line in code.strip().splitlines()]
    if '' in changes:
        result.append(('>', '', changes['']))
    return result


CASES = [
    (
        'measured_narrow_word_carrier',
        '''
void f(void *data, s32 unused, void *ctx) {
    u16 narrow;
    void *entry;
    entry = M2C_FIELD(ctx, void **, 20);
    narrow = M2C_FIELD(data, u16 *, 0);
    if (M2C_FIELD(entry, s32 *, 4) != narrow) {
        M2C_FIELD(entry, s32 *, 4) = (s32) narrow;
        if ((*M2C_FIELD(ctx, s32 **, 8) < 3) && (M2C_FIELD(data, s32 *, 4) == 1)) {
            M2C_FIELD(&state, s8 *, 11) = (s8) narrow;
        }
    }
}
''',
        '''
lhu $a1, ($a0)
lw $v0, 4($v1)
beq $v0, $a1, 56
nop
sw $a1, 4($v1)
lw $v0, 8($a2)
lw $v0, ($v0)
slti $v0, $v0, 3
beqz $v0, 56
addiu $v0, $zero, 1
lw $v1, 4($a0)
bne $v1, $v0, 56
nop
lui $at, %hi(state)
sb $a1, %lo(state)($at)
jr $ra
nop
''',
        {'': 'andi $v1, $a3, 65535'},
        ('u32 __repair_word;', '!= (__repair_word = narrow))', '(s32) __repair_word;', '(s8) __repair_word;'),
        ('(s8) narrow;', '(s8) other;'),
    ),
    (
        'measured_guarded_byte_copy',
        '''
void f(u8 *in, u8 *out, s32 count) {
    int zero;
    s32 i;
    u8 *src;
    u8 *dst;
    u8 byte;
    src = in; dst = out; i = 0; zero = 0;
    if (count > zero) {
        do {
            byte = *src; src += 1; i += 1; *dst = byte; dst += 1;
        } while (i < count);
    }
}
''',
        '''
addiu $sp, $sp, -8
blez $a2, 40
move $v1, $zero
lbu $v0, ($a0)
addiu $a0, $a0, 1
addiu $v1, $v1, 1
sb $v0, ($a1)
slt $v0, $v1, $a2
bnez $v0, 12
addiu $a1, $a1, 1
addiu $sp, $sp, 8
jr $ra
nop
''',
        {'jr $ra': '', '': 'jr $ra'},
        ('{ s32 i; for (i = 0; i < count; i++) { *out++ = *in++; } }',),
        ('dst += 1;', 'dst += 2;'),
    ),
    (
        'measured_terminated_stack_buffer',
        '''
void f(void) {
    M2C_UNK sp20;
    s8 sp24;
    void *item;
    item = fetch(2);
    sp24 = 0;
    format(&sp20, &pattern, M2C_FIELD(&state, u8 *, 8));
    paint(item, M2C_FIELD(item, s16 *, 6), M2C_FIELD(item, s16 *, 8), &sp20);
}
''',
        '''
addiu $sp, $sp, -48
sw $ra, 44($sp)
jal fetch
nop
move $s0, $v0
addiu $a0, $sp, 32
lui $a1, %hi(pattern)
addiu $a1, $a1, %lo(pattern)
jal format
sb $zero, 36($sp)
lh $a1, 6($s0)
lh $a2, 8($s0)
move $a0, $s0
jal paint
addiu $a3, $sp, 32
''',
        {'addiu $a0, $sp, 32': '', 'sb $zero, 36($sp)': 'addiu $a0, $sp, 32'},
        ('s8 __repair_text[5];', '__repair_text[4] = 0;', 'format(__repair_text,'),
        ('sp24 = 0;', 'sp24 = 1;'),
    ),
    (
        'measured_call_record_carrier',
        '''
extern void *root;
void f(void *entry) {
    s32 token;
    token = lock(1);
    ((Entry*)entry)->value = (s32) ((List*)root)->count;
    ((Entry*)entry)->head = (void *) ((List*)root)->head;
    ((List*)root)->head = entry;
    if (((List*)root)->tail == NULL) {
        ((List*)root)->tail = entry;
    }
    lock(token, root);
}
''',
        '''
jal lock
addiu $a0, $zero, 1
lui $a1, %hi(root)
lw $a1, %lo(root)($a1)
lw $v1, 20($a1)
sw $v1, 8($s0)
lw $v1, ($a1)
sw $v1, ($s0)
lw $v1, 4($a1)
bnez $v1, 44
sw $s0, ($a1)
sw $s0, 4($a1)
jal lock
move $a0, $v0
''',
        {'': 'lui $a1, %hi(root)'},
        ('__repair_record = root;', 'lock(token, __repair_record);'),
        ('lock(token, root);', 'unlock(token, root);'),
    ),
    (
        'measured_float_interpolation_load',
        '''
void f(void *cell) {
    f32 value;
    f32 result;
    value = M2C_FIELD(cell, f32 *, 12);
    result = ((8.0f - value) * 0.2f) + value;
    M2C_FIELD(cell, f32 *, 12) = result;
}
''',
        '''
lui $at, 16640
mtc1 $at, $f0
lwc1 $f4, 12($v1)
sub.s $f0, $f0, $f4
lui $at, 15948
ori $at, $at, 52429
mtc1 $at, $f2
nop
mul.s $f0, $f0, $f2
add.s $f0, $f0, $f4
swc1 $f0, 12($v1)
swc1 $f0, 16($v1)
jr $ra
nop
''',
        {'': 'lwc1 $f4, 12($v1)', 'lwc1 $f4, 12($v1)': 'nop'},
        ('value = M2C_FIELD(cell, f32 *, 12);',
         '((8.0f - (M2C_FIELD(cell, f32 *, 12))) * 0.2f) + (M2C_FIELD(cell, f32 *, 12))'),
        ('8.0f - value', '8.0f + value'),
    ),
    (
        'measured_cached_loop_bound',
        '''
s32 f(void *item) {
    int zero;
    s32 index;
    s32 result;
    void *cursor;
    result = 1;
    cursor = M2C_FIELD(&table, void **, 8);
    index = 0; zero = 0;
    if (M2C_FIELD(&counts, s32 *, 12) > zero) {
        do {
            index += 1;
            result &= -(M2C_FIELD(cursor, s32 *, 12) != M2C_FIELD(item, s32 *, 4));
            cursor += 20;
        } while ((index < M2C_FIELD(&counts, s32 *, 12)) & (result != 0));
    }
    return result;
}
''',
        '''
lui $t0, %hi(actual_count)
lw $t0, %lo(actual_count)($t0)
lui $a3, %hi(actual_table)
lw $a3, %lo(actual_table)($a3)
blez $t0, 76
move $a1, $zero
lw $a0, 4($a0)
lw $v0, 12($a3)
addiu $a1, $a1, 1
xor $v0, $v0, $a0
sltu $v0, $zero, $v0
negu $v0, $v0
and $a2, $a2, $v0
slt $v0, $a1, $t0
sltu $v1, $zero, $a2
and $v0, $v0, $v1
bnez $v0, 24
addiu $a3, $a3, 20
''',
        {'': 'move $t0, $v0'},
        ('__repair_count = M2C_FIELD(&counts, s32 *, 12);\n    cursor',
         'if (__repair_count > zero)', 'index < __repair_count'),
        ('cursor += 20;', 'cursor += 24;'),
    ),
]


@pytest.mark.parametrize('family,source,code,changes,expected,nearby', CASES, ids=[case[0] for case in CASES])
def test_measured_carriers(family, source, code, changes, expected, nearby):
    diff = rows(code, changes)
    if family == 'measured_call_record_carrier':
        diff.append(('>', '', 'lw $a1, %lo(root)($a1)'))
    [(label, fixed)] = variants(source, 'f', '', diff)
    assert label == family
    assert all(fragment in fixed for fragment in expected)
    assert not variants(source.replace(*nearby), 'f', '', diff)
    assert not variants(source, 'f', '', rows(code, {}))


def test_stack_buffer_leaves_an_existing_macro_alone():
    _, source, code, changes, _, _ = CASES[2]
    assert not variants(source, 'f', '#define __repair_text output', rows(code, changes))

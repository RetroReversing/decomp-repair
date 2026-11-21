from decomprepair.stack_fill_drafts import applies, rewrite

SOURCE = '''
void write_page(void *obj, s8 value) {
    M2C_UNK head;
    s8 tail;
    s32 count;
    s8 *cursor;
    count = 7;
    cursor = &tail;
    do {
        *cursor = value;
        count -= 1;
        cursor -= 1;
    } while (count >= 0);
    if (write_bytes(M2C_FIELD(obj, s32 *, 4), M2C_FIELD(obj, s32 *, 8), 16, &head, 0) == 0) {
        M2C_FIELD(obj, s8 *, 25) = value;
    }
}
'''
ASM = '''
addiu $sp, $sp, -48
sw $s0, 32($sp)
move $s0, $a0
sw $s1, 36($sp)
move $s1, $a1
addiu $v1, $zero, 7
addiu $v0, $sp, 31
sw $ra, 40($sp)
.Lfill:
sb $s1, ($v0)
addiu $v1, $v1, -1
bgez $v1, .Lfill
addiu $v0, $v0, -1
sw $zero, 16($sp)
lw $a0, 4($s0)
lw $a1, 8($s0)
addiu $a2, $zero, 16
jal write_bytes
addiu $a3, $sp, 24
beql $v0, $zero, .Ldone
sb $s1, 25($s0)
.Ldone:
lw $ra, 40($sp)
lw $s1, 36($sp)
lw $s0, 32($sp)
jr $ra
addiu $sp, $sp, 48
'''


def test_descending_fill_restores_the_buffer_extent_within_the_frame():
    assert applies(ASM)
    fixed = rewrite(SOURCE, 'write_page', ASM)
    assert fixed
    assert 's32 __repair_fill_buffer[2];' in fixed
    assert '((s8 *)__repair_fill_buffer)[count] = value;' in fixed
    assert '(M2C_UNK *)__repair_fill_buffer, 0) == 0' in fixed
    assert 'cursor' not in fixed
    assert not applies(ASM.replace('addiu $a3, $sp, 24', 'addiu $a3, $sp, 28'))
    assert not applies(ASM.replace('sw $ra, 40', 'sw $ra, 36').replace('lw $ra, 40', 'lw $ra, 36'))
    assert rewrite(SOURCE.replace('count = 7', 'count = 8'), 'write_page', ASM) is None
    assert rewrite(SOURCE.replace('== 0', '!= 0'), 'write_page', ASM) is None


ASCENDING_SOURCE = '''
void write_page(void *obj) {
    u8 sp18;
    u8 *cursor;
    cursor = &sp18;
    do {
        *cursor = M2C_FIELD(obj, u8 *, 25);
        cursor += 1;
    } while ((s32) cursor < (s32) &unksp20);
    write_bytes(M2C_FIELD(obj, s32 *, 4), M2C_FIELD(obj, s32 *, 8), 16, &sp18, 0);
}
'''
ASCENDING_ASM = '''
addiu $sp, $sp, -40
sw $ra, 32($sp)
addu $a1, $a0, $zero
addiu $v1, $sp, 24
addiu $a0, $sp, 32
.Lfill:
lbu $v0, 25($a1)
sb $v0, 0($v1)
addiu $v1, $v1, 1
slt $v0, $v1, $a0
bnez $v0, .Lfill
addiu $a2, $zero, 16
sw $zero, 16($sp)
lw $a0, 4($a1)
lw $a1, 8($a1)
jal write_bytes
addiu $a3, $sp, 24
lw $ra, 32($sp)
jr $ra
addiu $sp, $sp, 40
'''


def test_ascending_fill_uses_the_exclusive_end_to_recover_a_buffer():
    from decomprepair.stack_fill_drafts import ascending_applies, rewrite_ascending

    assert ascending_applies(ASCENDING_ASM)
    union = ASCENDING_SOURCE.replace(
        'u8 sp18;',
        '''union {
            unsigned char bytes[40];
            struct { unsigned char pad[24]; u8 value; } view_sp18;
            struct { unsigned char pad[32]; s32 value; } view_unksp20;
        } m2c_initial_frame;''',
    ).replace('&sp18', '&m2c_initial_frame.view_sp18.value').replace(
        '&unksp20', '&m2c_initial_frame.view_unksp20.value')
    for draft in (ASCENDING_SOURCE, union):
        fixed = rewrite_ascending(draft, 'write_page', ASCENDING_ASM)
        assert 'u8 __repair_fill_buffer[8];' in fixed
        assert '__repair_fill_buffer[__repair_fill_index] = M2C_FIELD(obj, u8 *, 25);' in fixed
        assert '__repair_fill_index < 8' in fixed
        assert '16, __repair_fill_buffer, 0);' in fixed
        assert 'cursor' not in fixed
    assert not ascending_applies(ASCENDING_ASM.replace('addiu $a0, $sp, 32', 'addiu $a0, $sp, 31'))
    assert rewrite_ascending(ASCENDING_SOURCE.replace('cursor += 1', 'cursor += 2'),
                             'write_page', ASCENDING_ASM) is None


def test_word_clear_uses_frame_size_and_reuses_counter_for_idle_loop():
    from decomprepair.stack_fill_drafts import rewrite_word_clear, word_clear_applies

    source = """
void f(void) {
    s32 *ptr;
    s32 count;
    ptr = sp;
    count = 4;
    do {
        *ptr = 0;
        count -= 1;
        ptr += 4;
    } while (count != 0);
    do {} while (1 != 0);
}
"""
    asm = """
addiu $sp, $sp, -64
move $v1, $sp
addiu $v0, $zero, 4
.Lfill:
sw $zero, ($v1)
addiu $v0, $v0, -1
bnez $v0, .Lfill
addiu $v1, $v1, 4
addiu $v0, $zero, 1
.Lidle:
bnez $v0, .Lidle
nop
jr $ra
addiu $sp, $sp, 64
"""
    assert word_clear_applies(asm)
    fixed = rewrite_word_clear(source, 'f', asm)
    assert 's32 __repair_clear_words[16];' in fixed
    assert 'ptr = __repair_clear_words;' in fixed
    assert 'ptr += 1;' in fixed
    assert 'count = 1;\n    do { } while (count != 0);' in fixed
    assert not rewrite_word_clear(source.replace('count = 4', 'count = 5'), 'f', asm)
    assert not word_clear_applies(asm.replace('bnez $v0, .Lidle', 'bnez $v0, .Lfill'))
    assert not word_clear_applies(asm.replace('addiu $v0, $zero, 4', 'addiu $v0, $zero, 17'))

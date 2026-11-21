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

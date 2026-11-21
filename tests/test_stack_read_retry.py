from decomprepair import stack_read_retry as repair

ASM = '''
addiu $sp, $sp, -40
sw $s0, 32($sp)
move $s0, $a0
sw $ra, 36($sp)
lbu $v0, 2($s0)
beqz $v0, .Lstart
nop
jal select_bank
move $a1, $zero
move $v1, $v0
addiu $v0, $zero, 3
bne $v1, $v0, .Lselected
move $a0, $s0
jal select_bank
move $a1, $zero
move $v1, $v0
.Lselected:
bnez $v1, .Lexit
move $v0, $v1
.Lstart:
lw $a0, 4($s0)
lw $a1, 8($s0)
addiu $a2, $zero, 5
jal read_page
addiu $a3, $sp, 16
move $v1, $v0
beqz $v1, .Lcompare
addiu $v0, $zero, 3
bne $v1, $v0, .Lexit
move $v0, $v1
lw $a0, 4($s0)
lw $a1, 8($s0)
addiu $a2, $zero, 5
jal read_page
addiu $a3, $sp, 16
move $v1, $v0
bnez $v1, .Lexit
nop
.Lcompare:
addiu $a0, $s0, 20
addiu $a1, $sp, 16
jal compare_data
addiu $a2, $zero, 16
sltu $v0, $zero, $v0
sll $v0, $v0, 1
.Lexit:
lw $ra, 36($sp)
lw $s0, 32($sp)
jr $ra
addiu $sp, $sp, 40
'''
DRAFT = '''
s32 verify(void *input) {
    M2C_UNK buf;
    s32 temp;
    s32 result;
    s32 bank;

    if (M2C_FIELD(input, u8 *, 2) != 0) {
        bank = select_bank(NULL);
        if (bank == 3) {
            bank = select_bank(input, 0);
        }
        result = bank;
        if (bank == 0) {
            goto read;
        }
    } else {
read:
        temp = read_page(M2C_FIELD(input, s32 *, 4), M2C_FIELD(input, s32 *, 8), 5, &buf);
        if ((temp == 0) || ((result = temp, (temp == 3)) &&
            (result = read_page(M2C_FIELD(input, s32 *, 4), M2C_FIELD(input, s32 *, 8), 5, &buf), (result == 0)))) {
            result = (compare_data(input + 20, &buf, 16) != 0) * 2;
        }
    }
    return result;
}
'''


def test_recovers_buffer_and_both_retry_calls():
    candidate = repair.rewrite(DRAFT, 'verify', ASM)
    assert 's32 __repair_read_buffer[4];' in candidate
    assert candidate.count('select_bank(input, 0)') == 2
    assert candidate.count('read_page(') == 2
    assert 'if (__repair_read_error != 3)' in candidate
    assert 'compare_data((char *)input + 20, __repair_read_buffer, 16)' in candidate


def test_rejects_wrong_stack_extent_and_changed_retry():
    assert repair.rewrite(DRAFT, 'verify', ASM.replace('$a2, $zero, 16', '$a2, $zero, 20')) is None
    assert repair.rewrite(DRAFT, 'verify', ASM.replace('bne $v1, $v0, .Lexit', 'beq $v1, $v0, .Lexit')) is None
    assert repair.rewrite(DRAFT.replace('temp == 3', 'temp == 4'), 'verify', ASM) is None

from decomprepair import split_dispatch_zero_case as repair

ASM = r'''
addiu $sp, $sp, -32
sw $s0, 16($sp)
move $s0, $a0
sw $ra, 20($sp)
lh $v1, 2($s0)
addiu $v0, $zero, 20
beq $v1, $v0, .Lfirst
slti $v0, $v1, 21
bnez $v0, .Lexit
move $v0, $zero
addiu $v0, $zero, 21
beq $v1, $v0, .Lsecond
addiu $v0, $zero, 22
beq $v1, $v0, .Lthird
move $v0, $zero
j .Lexit
nop
.Lfirst:
lui $a0, %hi(device)
jal query
addiu $a0, $a0, %lo(device)
j .Lfinish
nop
.Lsecond:
lbu $a1, 24($s0)
lw $a2, 8($s0)
lhu $a3, 26($s0)
lui $a0, %hi(device)
jal fetch
addiu $a0, $a0, %lo(device)
j .Lfinish
nop
.Lthird:
lbu $a1, 24($s0)
lw $a2, 8($s0)
lhu $a3, 26($s0)
lui $a0, %hi(device)
jal write
addiu $a0, $a0, %lo(device)
.Lfinish:
lw $a0, 4($s0)
move $a1, $zero
addiu $a2, $zero, 1
jal finish
sw $v0, 12($s0)
addiu $v0, $zero, 1
.Lexit:
lw $ra, 20($sp)
lw $s0, 16($sp)
jr $ra
addiu $sp, $sp, 32
'''
DRAFT = '''
s32 dispatch(void *request) {
    s16 kind;
    s32 status;
    s32 value;
    kind = M2C_FIELD(request, s16 *, 2);
    if (kind != 20) {
        status = 0;
        if (kind >= 21) {
            switch (kind) {
            case 21:
                value = fetch(&device, M2C_FIELD(request, u8 *, 24), M2C_FIELD(request, s32 *, 8), M2C_FIELD(request, u16 *, 26));
                goto join;
            case 22:
                value = write(&device, M2C_FIELD(request, u8 *, 24), M2C_FIELD(request, s32 *, 8), M2C_FIELD(request, u16 *, 26));
                goto join;
            default:
                return 0;
            }
        } else {
            return status;
        }
    } else {
        value = query(&device);
    join:
        M2C_FIELD(request, s32 *, 12) = value;
        finish(M2C_FIELD(request, s32 *, 4), 0, 1);
        status = 1;
        return status;
    }
}
'''


def test_explicit_zero_case_and_shared_completion():
    result = repair.rewrite(DRAFT, 'dispatch', ASM)
    assert 'case 0x13:\n        return 0;' in result
    assert result.index('query(&device)') < result.index('fetch(&device') < result.index('write(&device')
    assert 'finish(M2C_FIELD(request, s32 *, 4), 0, 1);\n    return 1;' in result
    assert 'goto' not in result


def test_rejects_different_edges_operands_and_return_behavior():
    assert repair.rewrite(DRAFT, 'dispatch', ASM.replace('j .Lfinish', 'j .Lexit', 1)) is None
    assert repair.rewrite(DRAFT, 'dispatch', ASM.replace('sw $v0, 12', 'sw $v0, 16')) is None
    assert repair.rewrite(DRAFT.replace('status = 0;', 'status = 2;'), 'dispatch', ASM) is None

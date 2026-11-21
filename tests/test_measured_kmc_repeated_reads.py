from decomprepair.measured_kmc_repeated_reads import variants


def test_poll_reloads_a_volatile_global():
    ops = '''
lui $v1, %hi(busy)
lw $v1, %lo(busy)($v1)
addiu $v0, $zero, 1
bne $v1, $v0, 40
nop
addiu $v1, $zero, 1
lui $v0, %hi(busy)
lw $v0, %lo(busy)($v0)
beq $v0, $v1, 24
nop
jr $ra
nop
'''.strip().splitlines()
    rows = [(' ', op, op) for op in ops]
    rows[6] = ('<', ops[6], '')
    rows[7] = ('<', ops[7], '')
    source = 'extern s32 busy;\nvoid f(void) { if (busy == 1) { do { } while (busy == 1); } }'
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_volatile_global_poll'
    assert 'extern volatile s32 busy;' in fixed and 'while (busy == 1) {}' in fixed
    assert not variants(source, 'f', 'extern s32 busy;', rows)
    assert not variants(source.replace('== 1', '== 2'), 'f', '', rows)


def test_branch_read_uses_address_verified_symbol():
    ops = '''
beqz $a0, 28
nop
lui $v0, %hi(word)
addiu $v0, $v0, %lo(word)
lw $v0, ($v0)
j f+40
xor $v0, $v0, $a0
lui $v0, %hi(word)
addiu $v0, $v0, %lo(word)
lw $v0, ($v0)
jr $ra
sltu $v0, $zero, $v0
'''.strip().splitlines()
    rows = [(' ', op, op) for op in ops]
    rows[3] = ('<', ops[3], '')
    source = '''
extern M2C_UNK base;
s32 f(s32 arg) {
    s32 value;
    if (arg != 0) { value = M2C_FIELD(&base, s32 *, 16) ^ arg; }
    else { value = M2C_FIELD(&base, s32 *, 16); }
    return value != 0;
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows, {'base': 100, 'word': 116}.get)
    assert label == 'measured_volatile_global_branch_read'
    assert 'extern s32 word;' in fixed
    assert fixed.count('*(volatile s32 *)&word') == 2
    assert not variants(source, 'f', '', rows, {'base': 100, 'word': 120}.get)
    assert not variants(source, 'f', '#define word other', rows, {'base': 100, 'word': 116}.get)

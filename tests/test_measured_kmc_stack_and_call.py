from decomprepair.measured_kmc_stack_and_call import variants


def test_adjacent_stack_words_form_one_array():
    ops = '''
addiu $sp, $sp, -48
sw $s2, 40($sp)
move $s2, $a0
sw $s1, 36($sp)
move $s1, $zero
sw $s0, 32($sp)
addiu $s0, $zero, 16
sw $ra, 44($sp)
sw $zero, 16($sp)
sw $zero, 20($sp)
sw $zero, 24($sp)
lw $a1, 128($s2)
addiu $s1, $s1, 1
move $a0, $s2
addiu $a2, $sp, 16
jal draw
addu $a1, $a1, $s0
sltiu $v0, $s1, 12
bnez $v0, 44
addiu $s0, $s0, 20
lw $ra, 44($sp)
lw $s2, 40($sp)
lw $s1, 36($sp)
lw $s0, 32($sp)
jr $ra
addiu $sp, $sp, 48
'''.strip().splitlines()
    rows = [(' ', op, op) for op in ops]
    rows[8] = ('<', ops[8], '')
    source = '''
void f(void *obj) {
    s32 sp10; s32 sp14; s32 sp18; s32 off; u32 i;
    i = 0; off = 0x10; sp10 = 0; sp14 = 0; sp18 = 0;
    do { i += 1; draw(obj, M2C_FIELD(obj, s32 *, 128) + off, &sp10); off += 0x14; }
    while (i < 0xCU);
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_three_word_stack_array'
    assert 's32 __repair_words[3];' in fixed
    assert '__repair_words[2] = 0;' in fixed and ', __repair_words)' in fixed
    assert not variants(source.replace('sp18 = 0', 'sp18 = 1'), 'f', '', rows)


def test_guarded_call_stages_first_argument_and_base():
    ops = '''
lui $v0, %hi(guard)
lw $v0, %lo(guard)($v0)
addiu $sp, $sp, -32
move $v1, $a0
beqz $v0, 56
sw $ra, 24($sp)
lbu $v0, 12($v1)
lui $a0, %hi(color)
lw $a0, %lo(color)($a0)
lbu $a1, 8($v1)
lbu $a2, 9($v1)
lbu $a3, 10($v1)
jal paint
sw $v0, 16($sp)
lw $ra, 24($sp)
jr $ra
addiu $sp, $sp, 32
'''.strip().splitlines()
    rows = [(' ', op, op) for op in ops] + [(' ', '', '')] * 2
    rows[3] = ('<', ops[3], '')
    source = '''
void f(void *obj) {
    if (M2C_FIELD(&state, s32 *, 16) != 0) {
        paint(M2C_FIELD(&state, s32 *, 24), M2C_FIELD(obj, u8 *, 8),
              M2C_FIELD(obj, u8 *, 9), M2C_FIELD(obj, u8 *, 10), (s32) M2C_FIELD(obj, u8 *, 12));
    }
}
'''
    symbols = {'state': 100, 'guard': 116, 'color': 124}
    [(label, fixed)] = variants(source, 'f', '', rows, symbols.get)
    assert label == 'measured_staged_guarded_color_call'
    assert '__repair_call_base = obj;' in fixed
    assert '__repair_call_first = M2C_FIELD(&state, s32 *, 24);' in fixed
    assert not variants(source, 'f', '', rows, {'state': 100, 'guard': 116, 'color': 125}.get)
    assert not variants(source.replace('obj, u8 *, 9', 'obj, u8 *, 11'), 'f', '', rows, symbols.get)

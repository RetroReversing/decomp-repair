from decomprepair.measured_kmc_branch_pointer import variants


def test_branch_pointer_is_captured_on_both_paths():
    ops = '''
addiu $sp, $sp, -24
sw $s0, 16($sp)
sw $ra, 20($sp)
jal disable
move $s0, $a0
andi $s0, $s0, 255
beqz $s0, 52
move $a0, $v0
lui $v1, %hi(pointer)
lw $v1, %lo(pointer)($v1)
lhu $v0, ($v1)
j f+68
ori $v0, $v0, 32
lui $v1, %hi(pointer)
lw $v1, %lo(pointer)($v1)
lhu $v0, ($v1)
andi $v0, $v0, 65503
jal restore
sh $v0, ($v1)
lw $ra, 20($sp)
lw $s0, 16($sp)
jr $ra
addiu $sp, $sp, 24
'''.strip().splitlines()
    rows = [(' ', op, op) for op in ops]
    rows += [('>', '', 'lui $v0, %hi(pointer)'), ('>', '', 'lw $v0, %lo(pointer)($v0)')]
    source = '''
extern u16 *pointer;
void f(s32 input) {
    s32 state;
    u16 value;
    state = disable();
    if (input & 0xFF) {
        value = *pointer | 0x20;
    } else {
        value = *pointer & 0xFFDF;
    }
    *pointer = value;
    restore(state);
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_branch_halfword_pointer'
    assert fixed.count('__repair_branch_pointer = (u16 *)pointer;') == 2
    assert '*__repair_branch_pointer = value;' in fixed
    assert not variants(source.replace('0xFFDF', '0xFFEF'), 'f', '', rows)
    assert not variants(source, 'f', '#define __repair_branch_pointer x', rows)

from decomprepair.measured_kmc_flag_update import variants


def test_branch_updates_flag_directly():
    ops = '''
beqz $v0, 72
addiu $v1, $zero, -5
lw $v0, 128($a0)
j f+80
ori $v0, $v0, 4
lw $v0, 128($a0)
and $v0, $v0, $v1
jr $ra
sw $v0, 128($a0)
'''.strip().splitlines()
    rows = [(' ', op, op) for op in ops] + [(' ', 'nop', 'nop')] * 13
    rows[1] = ('r', ops[1], 'addiu $v0, $zero, -5')
    rows[2] = ('r', ops[2], 'lw $v1, 128($a0)')
    rows[6] = ('r', ops[6], 'and $v0, $v1, $v0')
    rows[0] = ('|', ops[0], 'beql $v0, $zero, 72')
    source = '''
void f(void *obj) {
    s32 result;
    if (ready) {
        result = M2C_FIELD(obj, s32 *, 128) | 4;
    } else {
        result = M2C_FIELD(obj, s32 *, 128) & ~4;
    }
    M2C_FIELD(obj, s32 *, 128) = result;
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_direct_flag_update'
    assert 'M2C_FIELD(obj, s32 *, 128) |= 4;' in fixed
    assert 'M2C_FIELD(obj, s32 *, 128) &= ~4;' in fixed
    assert not variants(source.replace('& ~4', '& ~8'), 'f', '', rows)
    assert not variants(source.replace('result;', 'result; use(result);'), 'f', '', rows)

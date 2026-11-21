from decomprepair.measured_kmc_vector_square import variants


def test_square_fields_are_read_at_each_store():
    ops = '''
lw $v0, ($a0)
mult $v0, $v0
mflo $v0
sw $v0, ($a1)
nop
lw $v0, 4($a0)
mult $v0, $v0
mflo $v0
sw $v0, 4($a1)
nop
lw $v0, 8($a0)
mult $v0, $v0
mflo $v0
nop
nop
jr $ra
sw $v0, 8($a1)
'''.strip().splitlines()
    rows = [(' ', op, op) for op in ops]
    rows.insert(1, ('>', '', 'nop'))
    rows[6] = ('o', ops[5], '')
    rows[11] = ('o', ops[10], '')
    rows.insert(6, ('o', '', ops[5]))
    rows.insert(12, ('o', '', ops[10]))
    source = '''
void f(void *src, void *dst) {
    s32 a; s32 b; s32 c;
    a = M2C_FIELD(src, s32 *, 0);
    M2C_FIELD(dst, s32 *, 0) = (s32) (a * a);
    b = M2C_FIELD(src, s32 *, 4);
    M2C_FIELD(dst, s32 *, 4) = (s32) (b * b);
    c = M2C_FIELD(src, s32 *, 8);
    M2C_FIELD(dst, s32 *, 8) = (s32) (c * c);
}
'''
    [(label, fixed)] = variants(source, 'f', '', rows)
    assert label == 'measured_direct_vector_squares'
    assert fixed.count('M2C_FIELD(src, s32 *, 4)') == 2
    assert 's32 a;' not in fixed
    assert not variants(source.replace('(b * b)', '(b * a)'), 'f', '', rows)
    assert not variants(source.replace('void *src', 'volatile void *src'), 'f', '', rows)

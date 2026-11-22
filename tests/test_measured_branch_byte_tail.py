from decomprepair.measured_branch_byte_tail import variants

SOURCE = '''void update(void *obj) {
    if (M2C_FIELD(obj, u8 *, 0) != 0) {
        if (M2C_FIELD(obj, u8 *, 1) != 0) {
            M2C_FIELD(obj, u8 *, 16) = 10;
            M2C_FIELD(obj, s8 *, 18) = 30;
        } else {
            M2C_FIELD(obj, u8 *, 16) = 255;
            M2C_FIELD(obj, u8 *, 18) = 255;
        }
        M2C_FIELD(obj, u8 *, 19) = 255;
    }
}'''
T = ['addiu $v0, $zero, 30', 'sb $v0, 18($a0)', 'j update+44', 'addiu $v0, $zero, 255',
     'sb $v0, 16($a0)', 'sb $v0, 18($a0)', 'sb $v0, 19($a0)']
C = ['j update+40', 'addiu $v0, $zero, 30', 'sb $v0, 16($a0)', 'sb $v0, 18($a0)',
     'addiu $v0, $zero, 255', 'sb $v0, 19($a0)']
ROWS = [('r', T[i] if i < len(T) else '', C[i] if i < len(C) else '') for i in range(len(T))]


def test_distributes_tail_into_both_arms():
    label, fixed = variants(SOURCE, 'update', '', ROWS)[0]
    assert label == 'measured_branch_byte_tail'
    assert fixed.count('M2C_FIELD(obj, u8 *, 19) = 255;') == 2
    assert fixed.index('M2C_FIELD(obj, u8 *, 19) = 255;') < fixed.index('} else {')


def test_requires_same_store_and_side_effect_free_arm_shapes():
    assert not variants(SOURCE.replace('u8 *, 19', 'u8 *, 20'), 'update', '', ROWS)
    assert not variants(SOURCE.replace('u8 *, 19) = 255', 'u8 *, 19) = 254'), 'update', '', ROWS)
    assert not variants(SOURCE.replace('s8 *, 18) = 30;', 's8 *, 18) = 30; return;'), 'update', '', ROWS)
    assert not variants(SOURCE, 'update', '#define obj alias', ROWS)
    assert not variants(SOURCE, 'update', '', [('r', x, x) for x in T])

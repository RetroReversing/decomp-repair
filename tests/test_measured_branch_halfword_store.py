from decomprepair.measured_branch_halfword_store import variants

SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
void work(void *node, s32 condition) {
    s16 value;
    if (condition == 0) {
        value = 0xF;
    } else {
        value = 0x10;
    }
    M2C_FIELD(node, s16 *, 0) = value;
}
'''
TARGET = ['bnez $a2, 0x34', 'sw $a0, 0x14($s0)', 'j work+0x38',
          'addiu $v0, $zero, 0xf', 'addiu $v0, $zero, 0x10', 'sh $v0, ($s0)']
CANDIDATE = ['bnez $a2, 0x34', 'nop', 'addiu $v0, $zero, 0x10',
             'addiu $v0, $zero, 0xf', 'sh $v0, ($s0)']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         CANDIDATE[i] if i < len(CANDIDATE) else 'nop') for i in range(30)]


def test_distributes_store_into_both_arms():
    result = variants(SOURCE, 'work', '', ROWS)
    assert len(result) == 1
    assert 'M2C_FIELD(node, s16 *, 0) = 0xF;' in result[0][1]
    assert 'M2C_FIELD(node, s16 *, 0) = 0x10;' in result[0][1]
    assert 'M2C_FIELD(node, s16 *, 0) = value;' not in result[0][1]


def test_rejects_wrong_target_and_other_uses():
    assert not variants(SOURCE, 'work', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('0x10;', '0x11;'), 'work', '', ROWS)
    assert not variants(SOURCE.replace('= value;', '= value;\n    sink(value);'), 'work', '', ROWS)
    assert not variants(SOURCE.replace('void *node', 'volatile void *node'), 'work', '', ROWS)
    assert not variants(SOURCE.replace('value = 0xF;', '/* note */ value = 0xF;'), 'work', '', ROWS)

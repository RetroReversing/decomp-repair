from decomprepair.measured_guarded_flag_value import variants

SOURCE = '''extern M2C_UNK flags;
void update(void) {
    s32 old;
    s32 value;
    old = M2C_FIELD(&flags, s32 *, 0) & ~0x1800;
    value = old | 0x1800;
    if (M2C_FIELD(&flags, u8 *, -0xDD) != 1) {
        M2C_FIELD(&flags, s32 *, 0) = value;
    }
}
'''
TARGET = ['lui $a1, %hi(flags)', 'lbu $v1, -0xdd($a1)', 'addiu $v0, $zero, 1',
          'beq $v1, $v0, 0x6c', 'ori $v1, $a0, 0x1800', 'sw $v1, ($a1)']
CANDIDATE = ['ori $a1, $v0, 0x1800', 'lbu $v1, -0xdd($a0)']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         CANDIDATE[i] if i < len(CANDIDATE) else 'nop') for i in range(30)]


def test_delays_local_into_guard():
    result = variants(SOURCE, 'update', '', ROWS)
    assert len(result) == 1
    assert result[0][1].index('if (') < result[0][1].index('value = old | 0x1800;')


def test_requires_witness_and_no_later_use():
    assert not variants(SOURCE, 'update', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE.replace('    }\n}', '    }\n    use(value);\n}'), 'update', '', ROWS)
    assert not variants(SOURCE.replace('s32 value;', 'volatile s32 value;'), 'update', '', ROWS)
    assert not variants(SOURCE.replace('value = old', '/* note */ value = old'), 'update', '', ROWS)

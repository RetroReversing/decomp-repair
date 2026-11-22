from decomprepair.measured_float_argument_pair import variants

SOURCE = '''s8 compute(M2C_UNK, M2C_UNK, u8);
void work(void) {
    result = compute(0x437F0000, 0x40000000, value);
}
'''
TARGET = ['lui $at, 0x437f', 'mtc1 $at, $f12', 'lui $at, 0x4000',
          'mtc1 $at, $f14', 'lui $a2, %hi(value)', 'jal compute', 'lbu $a2, %lo(value)($a2)']
CANDIDATE = ['lui $a0, 0x437f', 'lui $a2, %hi(value)', 'lbu $a2, %lo(value)($a2)',
             'jal compute', 'lui $a1, 0x4000']
ROWS = [('r', TARGET[i] if i < len(TARGET) else 'nop',
         CANDIDATE[i] if i < len(CANDIDATE) else 'nop') for i in range(20)]


def test_recovers_two_float_register_arguments():
    result = variants(SOURCE, 'work', '', ROWS)
    assert len(result) == 1
    assert 'compute(f32, f32, u8)' in result[0][1]
    assert 'compute(255.0f, 2.0f, value)' in result[0][1]


def test_requires_literal_bits_witness_and_local_prototype():
    assert not variants(SOURCE.replace('0x40000000', '0x40400000'), 'work', '', ROWS)
    assert not variants(SOURCE, 'work', '', [('r', 'nop', right) for _, _, right in ROWS])
    assert not variants(SOURCE, 'work', 's8 compute(f32, f32, u8);', ROWS)
    assert not variants(SOURCE.replace('}\n', '    compute(0, 0, value);\n}\n'), 'work', '', ROWS)

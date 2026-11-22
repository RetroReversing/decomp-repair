from decomprepair import vector_accumulator_stage as repair

SOURCE = '''
extern f32 height;
void f(int state) {
    union { u32 word; f32 number; } zero;
    f32 buffer[3];
    f32 temp_s6;
    f32 var_s6;
    zero.word = 0;
    var_s6 = zero.number;
    if (state) {
        temp_s6 = 0.0f - height;
        height = new_height();
        fill(buffer, height);
        prepare();
        var_s6 = ((temp_s6 + height) + buffer[2]) + finish();
    }
    emit(var_s6);
}
'''

ROWS = [
    'jal fill',
    'addiu $a0, $sp, 0x20',
    'lwc1 $f0, 0x28($sp)',
    'mtc1 $s6, $f16',
    'nop',
    'add.s $f16, $f16, $f0',
    'mfc1 $s6, $f16',
    'jal prepare',
    'nop',
]


def asm(rows):
    return '\n'.join(f'/* {index*4:06X} {0x80000000+index*4:08X} 00000000 */ {op}'
                     for index, op in enumerate(rows))


def test_stages_vector_in_the_early_accumulator():
    [(family, candidate), (_, literal)] = repair.variants(SOURCE, 'f', asm(ROWS))
    assert family == repair.FAMILY
    assert 'var_s6 = zero.number - height;' in candidate
    assert 'var_s6 = 0.0f - height;' in literal
    assert 'fill(buffer, height);\n        var_s6 += height;\n        var_s6 += buffer[2];' in candidate
    assert 'var_s6 += finish();' in candidate


def test_requires_an_unclobbered_load_into_the_same_saved_register():
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:4] + ['mov.s $f0, $f12'] + ROWS[4:]))
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:6] + ['mfc1 $s7, $f16'] + ROWS[7:]))
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:2] + ['lwc1 $f0, 0x24($sp)'] + ROWS[3:]))


def test_does_not_reuse_an_unproven_zero_or_escaped_accumulator():
    for source in (SOURCE.replace('zero.word = 0;', 'zero.word = 1;'),
                   SOURCE.replace('zero.word = 0;', 'if (state) zero.word = 0;')):
        [(_, literal)] = repair.variants(source, 'f', asm(ROWS))
        assert 'var_s6 = 0.0f - height;' in literal
    escaped = SOURCE.replace('    if (state) {', '    keep(&var_s6);\n    if (state) {')
    assert not repair.variants(escaped, 'f', asm(ROWS))

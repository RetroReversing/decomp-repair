from decomprepair import vector_component_order as repair

SOURCE = '''
extern f32 height;
void f(void) {
    f32 vec[3];
    f32 var_s5;
    f32 var_s6;
    f32 var_fp;
    var_s5 = var_s6 = var_fp = 0.0f;
    fill(vec, 3);
    var_s5 += vec[0];
    var_s6 += height;
    var_s6 += vec[2];
    var_fp -= vec[1];
    emit(var_s5, var_fp, var_s6);
}
'''

ROWS = [
    'jal fill',
    'addiu $a0, $sp, 0x20',
    'lwc1 $f0, 0x20($sp)',
    'mtc1 $s5, $f16',
    'add.s $f16, $f16, $f0',
    'mfc1 $s5, $f16',
    'lwc1 $f0, 0x24($sp)',
    'mtc1 $fp, $f16',
    'sub.s $f16, $f16, $f0',
    'mfc1 $fp, $f16',
    'lwc1 $f0, 0x28($sp)',
    'mtc1 $s6, $f16',
    'add.s $f16, $f16, $f0',
    'mfc1 $s6, $f16',
]


def asm(rows):
    return '\n'.join(f'/* {index*4:06X} {0x80000000+index*4:08X} 00000000 */ {op}'
                     for index, op in enumerate(rows))


def test_recovers_vector_update_order_and_keeps_related_addition():
    [(family, text)] = repair.variants(SOURCE, 'f', asm(ROWS))
    assert family == repair.FAMILY
    assert 'var_s5 += vec[0];\n    var_fp -= vec[1];\n    var_s6 += height;\n    var_s6 += vec[2];' in text


def test_requires_three_unclobbered_components_and_the_correct_operation():
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:-1]))
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:8] + ['mtc1 $zero, $f0'] + ROWS[8:]))
    assert not repair.variants(SOURCE, 'f', asm(ROWS[:8] + ['add.s $f16, $f16, $f0'] + ROWS[9:]))


def test_leaves_other_work_and_aliases_in_source_order():
    for source in (SOURCE.replace('var_s6 += height;', 'touch();\n    var_s6 += height;'),
                   SOURCE.replace('extern f32 height;', 'extern volatile f32 height;'),
                   SOURCE.replace('fill(vec, 3);', 'keep(&var_fp);\n    fill(vec, 3);')):
        assert not repair.variants(source, 'f', asm(ROWS))

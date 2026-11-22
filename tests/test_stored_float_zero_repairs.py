from decomprepair import stored_float_zero_repairs as repair

FIELD = '*((f32 *) (((char *) arg0) + 0x44))'
SOURCE = f"""\
void f(void *arg0, int state) {{
    f32 sp5C;
    sp5C = 0.0f;
    switch (state) {{
    case 5:
        {FIELD} = 0.0f;
        break;
    }}
    {FIELD} = (f32) (({FIELD}) + 0.0f);
}}
"""


def assembly(*rows):
    return '\n'.join(f'/* {i*4:X} {0x80000000+i*4:08X} 00000000 */ {row}' for i, row in enumerate(rows))


TARGET = assembly(
    'addiu $sp, $sp, -0xf8',
    'addu $s2, $a0, $zero',
    'addu $s7, $zero, $zero',
    'sw $s7, 0x5c($sp)',
    'move $s7, $zero',
    'mtc1 $s7, $f16',
    'add.s $f2, $f2, $f16',
    'swc1 $f2, 0x44($s2)',
)


def test_splits_word_initialization_from_the_float_uses():
    [(family, candidate)] = repair.variants(SOURCE, 'f', TARGET)
    assert family == repair.FAMILY
    assert candidate.count('repair_saved_zero.bits = 0;') == 2
    assert candidate.index('repair_saved_zero.bits = 0;') < candidate.index('sp5C = 0.0f;')
    assert f'{FIELD} = repair_saved_zero.number;' in candidate
    assert '+ repair_saved_zero.number' in candidate


def test_requires_saved_zero_and_a_store_to_the_argument_field():
    for altered in (
        TARGET.replace('move $s7, $zero', 'move $s7, $v0'),
        TARGET.replace('swc1 $f2, 0x44($s2)', 'swc1 $f2, 0x40($s2)'),
        TARGET.replace('addu $s2, $a0, $zero', 'addu $s2, $a1, $zero'),
    ):
        assert not repair.variants(SOURCE, 'f', altered)


def test_skips_paths_bypassing_initialization_and_unbraced_resets():
    bypass = SOURCE.replace('    sp5C = 0.0f;', '    if (state) goto tail;\n    sp5C = 0.0f;').replace(
        f'    {FIELD} = (f32)', f'tail:\n    {FIELD} = (f32)')
    unbraced = SOURCE.replace(f'        {FIELD} = 0.0f;', f'        if (state) {FIELD} = 0.0f;')
    assert not repair.variants(bypass, 'f', TARGET)
    assert not repair.variants(unbraced, 'f', TARGET)

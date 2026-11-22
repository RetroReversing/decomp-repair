from decomprepair import range_case_switch_repairs as repair

SOURCE = '''
void f(void *record) {
    s16 mode;
    mode = *((s16 *) (((char *) record) + 0x7C));
    if ((mode == 0) || (mode == 6)) {
        act();
    }
    finish();
}
'''
ROWS = [
    'lh $v1, 0x7c($s2)',
    'beqz $v1, .L1',
    'addiu $v0, $zero, 6',
    'bne $v1, $v0, .L2',
    'nop',
]


def asm(rows):
    return '\n'.join(f'/* {index*4:06X} {0x80000000+index*4:08X} 00000000 */ {op}'
                     for index, op in enumerate(rows))


def choices(source, rows=ROWS):
    return [text for family, text in repair.variants(source, 'f', asm(rows))
            if family == repair.DISCRETE_FAMILY]


def test_recovers_shared_cases_from_the_target_compare_chain():
    [child] = choices(SOURCE)
    assert 'switch (mode)' in child
    assert 'case 0: case 6:' in child
    assert child.count('act();') == 1


def test_preserves_unproven_target_offset_value_and_register():
    assert not choices(SOURCE, ['lh $v1, 0x7e($s2)'] + ROWS[1:])
    assert not choices(SOURCE, ROWS[:2] + ['addiu $v0, $zero, 7'] + ROWS[3:])
    assert not choices(SOURCE, ROWS[:3] + ['bne $v1, $a1, .L2'] + ROWS[4:])


def test_preserves_outer_break_and_else():
    assert not choices(SOURCE.replace('act();', 'break;'))
    assert not choices(SOURCE.replace('    finish();', '    else cleanup();\n    finish();'))

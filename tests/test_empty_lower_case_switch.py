from decomprepair import switch_case_order_repairs as repair

SOURCE = '''
void f(void *object) {
    s32 state;
    state = read_byte((char *) object, 0x180);
    switch (state) {
    case 1:
        if (request()) goto clear;
        use();
        break;
    case 2:
        drop();
        break;
    }
clear:
    return;
}
'''

ROWS = [
    'lb $v1, 0x180($s1)',
    'addiu $v0, $zero, 1',
    'beq $v1, $v0, .L1',
    'slti $v0, $v1, 2',
    'bnez $v0, .L3',
    'addiu $v0, $zero, 2',
    'beq $v1, $v0, .L2',
]


def asm(rows):
    return '\n'.join(f'/* {index*4:06X} {0x80000000+index*4:08X} 00000000 */ {op}'
                     for index, op in enumerate(rows))


def choices(source, rows=ROWS):
    return [text for family, text in repair.variants(source, 'f', asm(rows))
            if family == repair.LOWER_EMPTY_FAMILY]


def test_inserts_noop_lower_case_when_target_has_extra_range_branch():
    [candidate] = choices(SOURCE)
    assert candidate == SOURCE.replace('    case 1:', '    case 0: break;\n    case 1:')


def test_requires_the_matching_field_load_and_range_evidence():
    assert not choices(SOURCE, ROWS[:3] + ROWS[5:])
    assert not choices(SOURCE.replace('0x180', '0x181'))
    assert not choices(SOURCE, ROWS[:3] + ['slti $v0, $v1, 3'] + ROWS[4:])


def test_does_not_add_a_noop_case_when_default_or_case_fallthrough_is_present():
    assert not choices(SOURCE.replace('    case 1:', '    default:\n    case 1:'))
    assert not choices(SOURCE.replace('        use();\n        break;', '        use();'))

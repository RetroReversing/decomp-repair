from decomprepair.stack_byte_init_repairs import variants

SOURCE = '''
void f(void) {
    M2C_UNK sp18;
    s8 sp1C;
    sp1C = 0;
    print_to(&sp18, &fmt, 1);
    render(obj, x, y, &sp18);
}
'''
CODE = [
    'addiu $sp, $sp, -40', 'sw $s0, 32($sp)', 'sw $ra, 36($sp)',
    'addiu $a0, $sp, 24', 'lui $a1, %hi(fmt)', 'addiu $a1, $a1, %lo(fmt)',
    'sb $zero, 28($sp)', 'jal print_to', 'li $a2, 1', 'lh $a1, 6($s0)',
    'lh $a2, 8($s0)', 'move $a0, $s0', 'jal render', 'addiu $a3, $sp, 24',
    'lw $ra, 36($sp)', 'jr $ra', 'addiu $sp, $sp, 40',
]


def rows(code):
    return [('<', line, '') if i == 6 else (' ', line, line) for i, line in enumerate(code)]


def test_byte_zero_is_kept_inside_the_measured_stack_buffer():
    [(family, fixed)] = variants(SOURCE, 'f', '', rows(CODE))
    assert family == 'measured_stack_buffer_byte_init'
    assert 'char __repair_print_buffer[8];' in fixed
    assert '__repair_print_buffer[4] = 0;' in fixed
    assert 'print_to((M2C_UNK *)__repair_print_buffer, &fmt, 1);' in fixed
    assert 'render(obj, x, y, (M2C_UNK *)__repair_print_buffer);' in fixed
    assert not variants(SOURCE.replace('&fmt', '&other'), 'f', '', rows(CODE))
    assert not variants(SOURCE, 'f', '', rows(CODE[:13]+['addiu $a3, $sp, 28']+CODE[14:]))
    assert not variants(SOURCE, 'f', '', rows(CODE[:6]+['sb $zero, 32($sp)']+CODE[7:]))

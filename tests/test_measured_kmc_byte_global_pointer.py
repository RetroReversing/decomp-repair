from decomprepair.measured_kmc_byte_global_pointer import variants

SOURCE = '''extern u8 value;
void f(void) {
    value -= 8;
    call(20);
}'''
TARGET = '''addiu $sp, $sp, -24
sw $ra, 16($sp)
lui $v1, %hi(value)
addiu $v1, $v1, %lo(value)
lbu $v0, ($v1)
addiu $v0, $v0, -8
sb $v0, ($v1)
jal call
addiu $a0, $zero, 20
lw $ra, 16($sp)
jr $ra
addiu $sp, $sp, 24'''.splitlines()
ROWS = [(' ', line, line) for line in TARGET]
ROWS[3] = ('<', TARGET[3], '')
ROWS.insert(6, ('>', '', 'lui $at, %hi(value)'))


def test_stages_byte_global_address():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_byte_global_pointer'
    assert '__repair_byte_ptr = &value;' in fixed
    assert '*__repair_byte_ptr -= 8;' in fixed
    assert 'call(20);' in fixed


def test_requires_measured_source_and_target():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('value -= 8', 'value -= 9'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('call(20)', 'call(21)'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('extern u8', 'extern volatile u8'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('extern u8', 'extern s32'), 'f', '', ROWS)

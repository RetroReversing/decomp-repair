from decomprepair.measured_kmc_variable_byte_cursor import variants

SOURCE = '''void *f(void *out, void *input) {
    short value;
    void *cursor;
    value = M2C_FIELD(input, u8 *, 0);
    cursor = input + 1;
    if (value & 0x80) {
        cursor += 1;
        value = M2C_FIELD(input, u8 *, 1) | ((value & 0x7F) << 8);
    }
    M2C_FIELD(out, s16 *, 0xA6) = (s16) value;
    return cursor;
}'''
TARGET = '''lbu $a2, ($a1)
andi $v0, $a2, 128
beqz $v0, 36
addiu $a1, $a1, 1
lbu $v1, ($a1)
addiu $a1, $a1, 1
andi $v0, $a2, 127
sll $v0, $v0, 8
or $a2, $v1, $v0
sh $a2, 166($a0)
jr $ra
move $v0, $a1'''.splitlines()
ROWS = [(' ', x, x) for x in TARGET]
ROWS[3] = ('r', TARGET[3], 'addiu $a3, $a1, 1')
ROWS[5] = ('<', TARGET[5], '')
ROWS.insert(4, ('>', '', 'addiu $a3, $a1, 2'))


def test_recover_one_or_two_byte_cursor():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_variable_byte_cursor'
    assert 'void *f(void *out, u8 *input)' in fixed
    assert fixed.count('*input++') == 2
    assert 'return input;' in fixed


def test_requires_matching_shape_and_instructions():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('0xA6', '0xA8'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('0x80', '0x40'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('void *cursor;', 'volatile void *cursor;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('return cursor;', 'return input;'), 'f', '', ROWS)

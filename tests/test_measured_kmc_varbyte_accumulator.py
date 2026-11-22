from decomprepair.measured_kmc_varbyte_accumulator import variants

SOURCE = '''u8 f(void *p) {
    u8 value;
    u8 byte;
    value = *p;
    do {
        value = (value << 7) + (byte & 0x7F);
    } while (byte & 0x80);
    return value;
}'''
ROWS = [(' ', 'nop', 'nop')] * 15 + [
    (' ', 'sll $a0, $a0, 7', 'sll $a0, $a0, 7'),
    (' ', 'andi $v0, $v1, 0x7f', 'andi $v0, $v1, 0x7f'),
    ('|', 'addu $a0, $a0, $v0', 'or $a0, $a0, $v0'),
    ('|', 'move $v0, $a0', 'andi $v0, $a0, 0xff')]


def test_widens_accumulator_and_return():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_varbyte_accumulator'
    assert fixed.startswith('u32 f(')
    assert 'u32 value;' in fixed
    assert 'u8 byte;' in fixed


def test_requires_matching_target_and_unescaped_accumulator():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE, 'f', 'u8 f(void *);', ROWS)
    assert not variants('u8 f(void *);\n' + SOURCE, 'f', '', ROWS)
    assert not variants(SOURCE.replace('return value;', 'return *(&value);'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('value << 7', 'value << 8'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('u8 value;', 'volatile u8 value;'), 'f', '', ROWS)

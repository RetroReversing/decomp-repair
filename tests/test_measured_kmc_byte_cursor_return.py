from decomprepair.measured_kmc_byte_cursor_return import variants

SOURCE = '''void *f(void *object, u8 *p) {
    u8 byte;
    byte = *p;
    M2C_FIELD(object, u8 *, 4) = byte;
    return p + 1;
}'''
ROWS = [(' ', 'lbu $v0, ($a1)', 'lbu $v0, ($a1)'),
        ('o', 'addiu $a1, $a1, 1', ''),
        ('i', 'move $v0, $a1', 'addiu $v0, $a1, 1')]


def test_advances_at_read():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_byte_cursor_return'
    assert 'byte = *p++;' in fixed
    assert 'return p;' in fixed


def test_requires_unused_cursor_and_target_schedule():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('return p + 1;', 'return p + 2;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('= byte;', '= *p;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('u8 *p', 'volatile u8 *p'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('u8 *p', 's32 *p'), 'f', '', ROWS)

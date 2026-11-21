from decomprepair.measured_kmc_byte_index_local import variants

SOURCE = '''s32 f(u8 arg) {
    s32 index;
    s32 second;
    u8 result;
    result = 0xFF;
    if ((arg & 0xFF) != 0xFF) {
        index = arg & 7;
        second = index & 0xFF;
        result = table[second];
        if (flag) result = other[index & 0xFF];
    }
    return result & 0xFF;
}'''
ROWS = [(' ', 'nop', 'nop')] * 20 + [
    ('>', '', 'move $a1, $a0'),
    ('r', 'andi $a0, $a0, 7', 'andi $a0, $a1, 7'),
    (' ', 'andi $v0, $a1, 255', 'andi $v0, $a0, 255')]


def test_narrows_bounded_index():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_masked_byte_index'
    assert 'u8 index;' in fixed
    assert 'index = arg & 7;' in fixed


def test_requires_bounded_unmodified_index_and_target():
    assert not variants(SOURCE.replace('arg & 7', 'arg & 0xFFFF'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('second = index', 'index++; second = index'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('second = index', 'escape(&index); second = index'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('u8 arg', 's32 arg'), 'f', '', ROWS)
    assert not variants(SOURCE, 'f', '', ROWS[:-1])

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


def test_reuses_masked_copy_without_changing_its_value():
    candidates = dict(variants(SOURCE, 'f', '', ROWS))
    fixed = candidates['measured_masked_byte_index_reuse']
    assert 'u8 index;' in fixed
    assert 's32 second;' not in fixed
    assert 'second = index' not in fixed
    assert 'table[(index & 0xFF)]' in fixed


def test_reuse_requires_unmodified_unescaped_copy():
    for source in (SOURCE.replace('result = table[second]', 'second++; result = table[second]'),
                   SOURCE.replace('result = table[second]', 'escape(&second); result = table[second]'),
                   SOURCE.replace('result = 0xFF;', 'result = second;')):
        assert 'measured_masked_byte_index_reuse' not in dict(variants(source, 'f', '', ROWS))
    assert 'measured_masked_byte_index_reuse' not in dict(variants(SOURCE, 'f', '#define second x', ROWS))

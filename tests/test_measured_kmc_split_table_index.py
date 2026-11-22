from decomprepair.measured_kmc_split_table_index import variants

SOURCE = '''extern s16 selector;
s32 f(u8 arg) {
    u8 value;
    u8 result;
    s32 index;
    value = arg & 7;
    index = value & 0xFF;
    if (selector == 1) {
        result = *(first + index);
    } else {
        result = *(second + index);
    }
    return result;
}'''
ROWS = [(' ', 'nop', 'nop')] * 23 + [
    (' ', 'lui $a0, %hi(selector)', 'lui $a0, %hi(selector)'),
    (' ', 'lui $a1, %hi(first)', 'lui $a1, %hi(first)'),
    (' ', 'lui $a1, %hi(second)', 'lui $a1, %hi(second)'),
    ('r', 'andi $v0, $a0, 255', 'andi $a0, $a0, 255'),
    ('r', 'addu $a1, $a1, $v0', 'addu $a1, $a1, $a0')]


def test_split_pure_index_into_each_branch():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_split_table_index'
    assert fixed.count('index = value & 0xFF;') == 2
    assert fixed.index('if (selector') < fixed.index('index = value')
    assert fixed.index('index = value') < fixed.index('result = *(first')


def test_requires_evidence_pure_guard_and_byte_input():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('u8 value;', 's32 value;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('extern s16 selector;', 'extern volatile s16 selector;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('value = arg & 7', 'value = arg & 15'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('selector == 1', 'selector++ == 1'), 'f', '', ROWS)

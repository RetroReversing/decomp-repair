from decomprepair.measured_kmc_indexed_byte_table import variants

SOURCE = '''extern M2C_UNK table;
int f(int index) {
    return *(&table + (index & 0xFF)) & 4;
}'''
ROWS = [('>', '', 'sll $v0, $v0, 2'),
        ('|', 'lbu $v0, %lo(table)($at)', 'lw $v0, %lo(table)($at)')]


def test_reads_target_byte_table_without_word_scaling():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_indexed_byte_table'
    assert '*((u8 *)&table + (index & 0xFF))' in fixed


def test_requires_matching_width_symbol_and_safe_index():
    assert not variants(SOURCE, 'f', '', ROWS[1:])
    assert not variants(SOURCE, 'f', '', [ROWS[0], ('|', 'lbu $v0, %lo(other)($at)', ROWS[1][2])])
    assert not variants(SOURCE.replace('index & 0xFF', 'index++ & 0xFF'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('extern M2C_UNK', 'extern volatile M2C_UNK'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('extern M2C_UNK', 'extern u8'), 'f', '', ROWS)

from decomprepair.measured_kmc_halfword_flag_table import variants

SOURCE = '''extern char flags[];
void f(int index) {
    int offset = index * 100;
    *(flags + offset) = *(flags + offset) | 0x10;
}'''
ROWS = [('|', 'lhu $v1, %lo(flags)($v1)', 'lbu $v1, %lo(flags)($v1)'),
        ('|', 'sh $v1, %lo(flags)($at)', 'sb $v1, %lo(flags)($at)')]


def test_uses_halfword_for_both_accesses():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_halfword_flag_table'
    assert fixed.count('*(u16 *)(flags + offset)') == 2


def test_requires_both_accesses_to_match_the_same_target_table():
    assert not variants(SOURCE, 'f', '', ROWS[:1])
    assert not variants(SOURCE.replace('extern char flags[];', 'extern volatile char flags[];'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('flags + offset) |', 'flags + index) |'), 'f', '', ROWS)
    assert not variants(SOURCE, 'f', '', [ROWS[0], (ROWS[1][0], ROWS[1][1].replace('flags', 'other'), ROWS[1][2])])
    assert not variants(SOURCE.replace('extern char flags[];', 'extern int flags[];'), 'f', '', ROWS)

from decomprepair.measured_kmc_inferred_table_widths import variants

SOURCE = '''extern char flags[];
extern char entries[];
int f(int i, int j) {
    if (*(flags + (i * 100)))
        return *(entries + (j * 4));
    return 0;
}'''
ROWS = [('|', 'lhu $v0, %lo(flags)($at)', 'lb $v0, %lo(flags)($at)'),
        ('|', 'lw $v0, %lo(entries)($at)', 'lb $v0, %lo(entries)($at)')]


def test_offers_combined_and_individual_widths():
    result = variants(SOURCE, 'f', '', ROWS)
    assert len(result) == 3
    assert '*(u16 *)(flags + (i * 100))' in result[0][1]
    assert '*(u32 *)(entries + (j * 4))' in result[0][1]
    assert '*(entries + (j * 4))' in result[1][1]


def test_only_changes_evidenced_simple_reads():
    assert len(variants(SOURCE, 'f', '', ROWS[:1])) == 1
    assert not variants(SOURCE, 'f', '', [('|', 'lhu $v0, %lo(other)($at)', ROWS[0][2])])
    assert not variants(SOURCE.replace('extern char flags[];', 'extern volatile char flags[];'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('i * 100', 'i++ * 100'), 'f', '', ROWS[:1])
    assert not variants(SOURCE.replace('extern char flags[];', 'extern int flags[];'), 'f', '', ROWS[:1])


def test_does_not_change_a_store_without_store_evidence():
    source = SOURCE.replace('if (*(flags + (i * 100)))', '*(flags + (i * 100)) = 1; if (i)')
    assert not variants(source, 'f', '', ROWS[:1])


def test_does_not_change_an_incremented_cell():
    source = SOURCE.replace('if (*(flags + (i * 100)))', '++*(flags + (i * 100)); if (i)')
    assert not variants(source, 'f', '', ROWS[:1])

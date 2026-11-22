from decomprepair.measured_kmc_indirect_byte_table import variants

SOURCE = '''extern char records[];
void f(int arg) {
    int index;
    index = arg & 0xFFFF;
    if (*(s32 *)*(records + (index * 100)) == 0) call(index);
}'''
ROWS = [('o', 'sw $ra, 0x10($sp)', ''),
        ('o', '', 'sw $ra, 0x10($sp)'),
        ('o', '', 'lb $v0, %lo(records)($at)'),
        ('i', 'lw $v0, %lo(records)($at)', 'lw $v0, ($v0)'),
        ('<', 'lbu $v0, ($v0)', '')]


def test_offers_typed_and_scoped_candidates():
    result = variants(SOURCE, 'f', '', ROWS)
    assert len(result) == 2
    assert '**(u8 **)(records + (index * 100))' in result[0][1]
    assert 'do { index = arg & 0xFFFF; } while (0);' in result[1][1]


def test_requires_pointer_then_byte_evidence_and_simple_source():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE, 'f', '', ROWS[:2] + ROWS[3:])
    assert not variants(SOURCE.replace('index * 100', 'index++ * 100'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('extern char', 'extern volatile char'), 'f', '', ROWS)
    assert len(variants(SOURCE, 'f', '', ROWS[2:])) == 1

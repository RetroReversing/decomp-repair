from decomprepair.measured_kmc_event_field_order import variants

SOURCE = '''void f(void *a, void *b, s32 value) {
    void *record;
    record = allocate();
    M2C_FIELD(record, s32 *, 0xC) = (s32) (value & 0xFF);
    M2C_FIELD(record, s16 *, 8) = 0xC;
    call(record);
}'''
ROWS = [(' ', 'nop', 'nop')] * 30 + [
    (' ', 'addiu $v0, $zero, 12', 'addiu $v0, $zero, 12'),
    (' ', 'sh $v0, 8($a2)', 'sh $v0, 8($a2)'),
    ('o', 'andi $v0, $s2, 255', ''), ('o', 'sw $v0, 12($a2)', '')]


def test_reorders_disjoint_fields():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_disjoint_event_field_order'
    assert fixed.index('s16 *, 8') < fixed.index('s32 *, 0xC')


def test_requires_evidence_disjoint_fields_and_simple_value():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('s16 *, 8', 's16 *, 0xC'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('value & 0xFF', 'value++ & 0xFF'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('void *record;', 'volatile void *record;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('0xC;', '0xD;'), 'f', '', ROWS)

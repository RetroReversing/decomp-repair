from decomprepair.measured_kmc_field_pointer import variants

SOURCE = '''void f(void *arg) {
    void *entry;
    s32 value;
    entry = M2C_FIELD(arg, void **, 0x48);
    value = M2C_FIELD(entry, s32 *, 0);
    if (value == 7) {
        M2C_FIELD(entry, s32 *, 0x20) = value;
    } else {
        call(value);
    }
    M2C_FIELD((entry + 4), s8 *, 7) = 0;
}'''
ROWS = [(' ', 'jal helper', 'jal helper'),
        ('o', 'addiu $s1, $v1, 4', 'slti $v0, $a0, 4'),
        ('i', 'sb $zero, 7($s1)', 'sb $zero, 11($s1)'),
        ('i', 'sb $zero, 7($s1)', 'sb $zero, 11($s1)')] + [(' ', 'nop', 'nop')] * 26


def test_live_pointer_is_saved_at_original_assignment():
    result = variants(SOURCE, 'f', '', ROWS)
    assert result[0][0] == 'measured_live_field_pointer'
    fixed = result[0][1]
    assert fixed.index('__repair_field_ptr = entry + 4;') < fixed.index('call(value)')
    assert 'M2C_FIELD(__repair_field_ptr, s8 *, 7)' in fixed


def test_requires_target_and_unchanged_pointer():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('call(value);', 'entry = 0; call(value);'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('call(value);', 'call(&entry);'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('call(value);', '++entry; call(value);'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('void *entry;', 'volatile void *entry;'), 'f', '', ROWS)

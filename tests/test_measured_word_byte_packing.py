from decomprepair.measured_word_byte_packing import variants

SOURCE = '''void pack(u8 value, void *dst) {
    M2C_FIELD(dst, s8 *, 5) = (s8) (value >> 8);
    M2C_FIELD(dst, u8 *, 0) = value;
    M2C_FIELD(dst, s8 *, 4) = (s8) (value >> 0x10);
    M2C_FIELD(dst, s8 *, 1) = (s8) (value >> 0x18);
}'''
T = ['srl $v0, $a0, 8', 'sb $v0, 5($a1)', 'srl $v0, $a0, 16', 'sb $a0, ($a1)',
     'srl $a0, $a0, 24', 'sb $v0, 4($a1)', 'jr $ra', 'sb $a0, 1($a1)']
ROWS = [('r', line, '') for line in T]


def test_widens_the_value_to_match_the_four_byte_stores():
    label, candidate = variants(SOURCE, 'pack', '', ROWS)[0]
    assert label == 'measured_word_byte_packing'
    assert 'void pack(u32 value, void *dst)' in candidate
    assert candidate.count('M2C_FIELD') == 4


def test_requires_matching_stores_and_no_conflicting_declarations():
    assert not variants(SOURCE.replace('s8 *, 5', 's8 *, 6'), 'pack', '', ROWS)
    assert not variants(SOURCE.replace('value >> 8', 'value >> 7'), 'pack', '', ROWS)
    assert not variants(SOURCE, 'pack', 'void pack(u8, void *);', ROWS)
    assert not variants(SOURCE, 'pack', '#define value alias', ROWS)
    assert not variants(SOURCE, 'pack', '', ROWS[:-1])

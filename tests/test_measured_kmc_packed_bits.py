from decomprepair.measured_kmc_packed_bits import variants

SOURCE = '''void f(void *arg) {
    s32 value;
    u16 word;
    void *dest;
    word = M2C_FIELD(arg, u16 *, 0x7A);
    value = word & 0x1F;
    if (value != 0) {
        dest = M2C_FIELD(arg, void **, 0x18);
        M2C_FIELD(dest, s32 *, 0) = (s32) ((value << 0xC) | ((value * 2) | 0x01000000));
    }
}'''
TARGET = '''andi $v0, $s0, 31
beqz $v0, 96
sll $a0, $v0, 12
lw $s1, 24($s2)
sll $v0, $v0, 1
lui $v1, 256
or $v0, $v0, $v1
or $a0, $a0, $v0
sw $a0, ($s1)'''.splitlines()
ROWS = [(' ', line, line) for line in TARGET] + [(' ', 'nop', 'nop')] * 20 + [
    ('<', 'sll $v0, $v0, 1', ''), ('>', '', 'sll $v1, $a0, 1')]


def test_regroups_masked_packed_value():
    result = variants(SOURCE, 'f', '', ROWS)
    assert len(result) == 1
    assert result[0][0] == 'measured_packed_bit_schedule'
    assert '(((value << 12) | 0x01000000) | (value << 1))' in result[0][1]


def test_requires_matching_evidence_and_safe_mask():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('& 0x1F', '& 0xFFFF'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('if (value', 'value++; if (value'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('if (value', 'escape(&value); if (value'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('s32 value;', 'volatile s32 value;'), 'f', '', ROWS)

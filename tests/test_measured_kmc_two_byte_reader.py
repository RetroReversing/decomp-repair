from decomprepair.measured_kmc_two_byte_reader import variants

SOURCE = '''s16 f(void *stream) {
    void *p;
    p = M2C_FIELD(stream, void **, 8);
    M2C_FIELD(stream, void **, 8) = (void *) (p + 2);
    M2C_FIELD(stream, void **, 8) = (void *) (p + 1);
    return (s16) ((M2C_FIELD(p, u8 *, 0) << 8) | M2C_FIELD(p, u8 *, 1));
}'''
TARGET = '''lw $a1, 8($a0)
addiu $v0, $a1, 1
sw $v0, 8($a0)
lbu $v0, ($a1)
addiu $v1, $a1, 2
sw $v1, 8($a0)
lbu $v1, 1($a1)
sll $v0, $v0, 8
or $v0, $v0, $v1
sll $v0, $v0, 16
jr $ra
sra $v0, $v0, 16'''.splitlines()
ROWS = [(' ', line, line) for line in TARGET]
ROWS[4] = ('<', TARGET[4], '')
ROWS[5] = ('<', TARGET[5], '')


def test_restores_ordered_byte_loads_and_updates():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_two_byte_reader_order'
    assert fixed.index('(p + 1)') < fixed.index('__repair_first =') < fixed.index('(p + 2)')
    assert fixed.index('(p + 2)') < fixed.index('__repair_second =')
    assert 'return (s16) ((__repair_first << 8) | __repair_second);' in fixed


def test_requires_matching_evidence_and_reader_shape():
    assert not variants(SOURCE, 'f', '', ROWS[:-1])
    assert not variants(SOURCE.replace('void **, 8', 'void **, 12'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('(p + 2)', '(p + 3)'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('void *p;', 'volatile void *p;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('s16 f(', 's32 f('), 'f', '', ROWS)

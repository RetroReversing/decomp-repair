"""Balance a byte selector's removed mask with a witnessed increment copy."""

from decomprepair.balanced_signed_selector_increment import FAMILY, variants

SOURCE = '''
static inline s8 byte_at(char *p, int offset)
{
    return *((s8 *) (p + offset));
}
void adjust(char *record)
{
    unsigned short mode;
    s16 snapshot;
    s8 count;
    mode = byte_at((char *) record, 0x17e);
    switch (mode) {
    case 0: case 1: break;
    case 2: case 3: act(); break;
    }
    count = byte_at((char *) record, 0x307);
    *((u8 *) (((char *) record) + 0x197)) = 0xfU;
    if (count < 100) {
        *((s8 *) (((char *) record) + 0x307)) = (s8) (count + 1);
    }
}
'''
ROWS = [
    ('r', 'lb $v1, 0x17e($s1)', 'lb $v0, 0x17e($s1)'),
    ('>', '', 'andi $v1, $v0, 0xffff'),
    ('|', 'bltz $v1, 0x210 [bytes 04600043]', 'bltz $v1, 0x210 [bytes 04600042]'),
    (' ', 'slti $v0, $v1, 2', 'slti $v0, $v1, 2'),
    ('|', 'bnez $v0, 0x210 [bytes 14400041]', 'bnez $v0, 0x210 [bytes 14400040]'),
    (' ', 'slti $v0, $v1, 4', 'slti $v0, $v1, 4'),
    ('|', 'beqz $v0, 0x210 [bytes 1040003f]', 'beqz $v0, 0x210 [bytes 1040003e]'),
    (' ', 'nop', 'nop'),
    (' ', 'lb $v1, 0x307($s1)', 'lb $v1, 0x307($s1)'),
    (' ', 'sb $v0, 0x197($s1)', 'sb $v0, 0x197($s1)'),
    ('<', 'move $v0, $v1', ''),
    ('r', 'slti $v1, $v1, 0x64', 'slti $v0, $v1, 0x64'),
    ('r', 'beqz $v1, 0x320', 'beqz $v0, 0x320'),
    ('r', 'addiu $v0, $v0, 1', 'addiu $v0, $v1, 1'),
    (' ', 'sb $v0, 0x307($s1)', 'sb $v0, 0x307($s1)'),
]


def test_pairs_signed_selector_with_precomparison_snapshot():
    [(family, changed)] = variants(SOURCE, 'adjust', ROWS)
    assert family == FAMILY
    assert 's8 mode;' in changed
    assert 'snapshot = count;\n    count = (count < 100);\n    if (count)' in changed
    assert '(s8) (snapshot + 1)' in changed


def test_rejects_incomplete_witness_or_nonmatching_fields():
    assert not variants(SOURCE, 'adjust', ROWS[:8])
    assert not variants(SOURCE, 'adjust', ROWS[8:])
    assert not variants(SOURCE.replace('0x307', '0x308'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('case 0:', 'case 65535:'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('return *((s8 *) (p + offset));', 'return foo(p, offset);'), 'adjust', ROWS)


def test_refuses_live_snapshot_and_count_with_additional_uses():
    assert not variants(SOURCE.replace('count + 1);', 'count + 1);\n        observe(snapshot);'), 'adjust', ROWS)
    assert not variants(SOURCE.replace('count + 1);', 'count + 1);\n        observe(count);'), 'adjust', ROWS)

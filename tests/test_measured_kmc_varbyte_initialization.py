from decomprepair.measured_kmc_varbyte_initialization import variants

SOURCE = '''s32 f(s32 x, s32 y) {
    s32 first;
    s32 byte;
    s32 acc;
    s32 unused;
    first = read() & 0xFF;
    unused = first;
    if (first & 0x80) {
        acc = first & 0x7F;
        do {
            byte = read(x, y) & 0xFF;
            acc = (acc << 7) + (byte & 0x7F);
        } while (byte & 0x80);
        unused = acc;
    }
    return acc;
}'''
ROWS = [('|', 'andi $s0, $v0, 0xff', 'move $v1, $v0'),
        ('<', 'andi $v0, $v0, 0xff', '')]


def test_initializes_accumulator_and_narrows_both_reads():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_varbyte_initialization'
    assert 'acc = (u8) read();' in fixed
    assert 'byte = (u8) read(x, y);' in fixed
    assert 'unused' not in fixed


def test_requires_full_shape_and_target_evidence():
    assert not variants(SOURCE, 'f', '', ROWS[:1])
    assert not variants(SOURCE.replace('unused = acc;', 'use(unused);'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('read(x, y)', 'other(x, y)'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('s32 acc;', 'volatile s32 acc;'), 'f', '', ROWS)
    assert not variants(SOURCE, 'f', '#define read other', ROWS)

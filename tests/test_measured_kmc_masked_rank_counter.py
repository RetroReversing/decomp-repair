from decomprepair.measured_kmc_masked_rank_counter import variants

SOURCE = '''s32 f(void *p) {
    s32 rank;
    s32 index;
    rank = 4;
    index = 0;
    do {
        if (test(p, index)) rank -= 1;
        index += 1;
    } while ((u32) (index & 0xFF) < 4U);
    return (rank - 1) & 0xFF;
}'''
ROWS = [('|', 'bnel $v0, $zero, 0x50', 'subu $a2, $a2, $v0'),
        ('<', 'addiu $a2, $a2, -1', '')]


def test_uses_byte_counter_for_bounded_masked_result():
    label, fixed = variants(SOURCE, 'f', '', ROWS)[0]
    assert label == 'measured_masked_rank_counter'
    assert 'u8 rank;' in fixed


def test_requires_restricted_uses_bound_and_target():
    assert not variants(SOURCE, 'f', '', ROWS[:1])
    assert not variants(SOURCE.replace('rank = 4;', 'rank = 5;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('rank = 4;', 'rank = 4; use(rank);'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('index += 1;', 'index += 1; index = 8;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('< 4U', '< 8U'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('index += 1;', 'index += 1; ++index;'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('test(p, index)', 'test(p, &index)'), 'f', '', ROWS)
    assert not variants(SOURCE.replace('s32 rank;', 'volatile s32 rank;'), 'f', '', ROWS)

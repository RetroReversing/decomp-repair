from decomprepair import fixed_blend_staging as repair

HEADER = 'typedef signed int s32; typedef signed short s16; typedef signed char s8;'
SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
void f(void *left, void *right, s32 first, s32 second, void *out) {
    s32 sum0; s32 sum1; s32 sum2;
    s32 round0; s32 round1; s32 round2;
    sum0 = (M2C_FIELD(left, s16 *, 0) * first) + (M2C_FIELD(right, s16 *, 0) * second);
    round0 = sum0;
    if (sum0 < 0) { round0 = sum0 + 0xFFF; }
    M2C_FIELD(out, s16 *, 0) = (s16) (round0 >> 0xC);
    sum1 = (M2C_FIELD(left, s16 *, 2) * first) + (M2C_FIELD(right, s16 *, 2) * second);
    round1 = sum1;
    if (sum1 < 0) { round1 = sum1 + 0xFFF; }
    M2C_FIELD(out, s16 *, 2) = (s16) (round1 >> 0xC);
    sum2 = (M2C_FIELD(left, s16 *, 4) * first) + (M2C_FIELD(right, s16 *, 4) * second);
    round2 = sum2;
    if (sum2 < 0) { round2 = sum2 + 0xFFF; }
    M2C_FIELD(out, s16 *, 4) = (s16) (round2 >> 0xC);
}
'''
ROWS = [('r', 'mult $v0, $a2', 'mult $v1, $a2')] * 6 + [('r', 'sra $v1, $v0, 0xc', 'sra $v0, $v0, 0xc')] * 3


def test_stages_products_and_reuses_gain_after_its_last_read():
    (_, candidate), = repair.variants(SOURCE, 'f', ROWS, header=HEADER)
    assert 'sum0 = (M2C_FIELD(left, s16 *, 0) * first); sum0 +=' in candidate
    assert 'sum2 = (M2C_FIELD(left, s16 *, 4) * first); first = sum2;' in candidate
    assert 'first = round2 >> 0xC; M2C_FIELD(out, s16 *, 4) = (s16) first;' in candidate


def test_rejects_changes_that_make_staging_unsafe_or_unrelated():
    assert not repair.variants(SOURCE, 'f', ROWS[:-1], header=HEADER)
    assert not repair.variants(SOURCE.replace('round1 = sum1;', 'round1 = sum1; side();'), 'f', ROWS, header=HEADER)
    assert not repair.variants(SOURCE, 'f', ROWS, header=HEADER + '\n#define sum0 observable')
    assert not repair.variants(SOURCE.replace('sum0 =', '/* retain this */ sum0 =', 1), 'f', ROWS, header=HEADER)
    assert not repair.variants(SOURCE, 'f', ROWS, header=HEADER.replace('signed int', 'volatile int'))

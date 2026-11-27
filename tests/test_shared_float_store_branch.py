from decomprepair import shared_float_store_branch as repair

HEADER = '#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))'
ASM = 'bc1tl .L1\nsb $zero, 8($s3)\n'
SOURCE = '''void f(char *p) {
    if (M2C_FIELD(p, f32 *, 4) > 0.0f) {
        if (!(M2C_FIELD(p, f32 *, 4) < 1.5f)) {
        } else {
            M2C_FIELD(p, u8 *, 8) = 0U;
        }
    } else if (-M2C_FIELD(p, f32 *, 4) < 1.5f) {
        M2C_FIELD(p, u8 *, 8) = 0U;
    }
}
'''


def test_join_identical_stores_without_changing_float_tests():
    out = repair.variants(SOURCE, 'f', ASM, HEADER)
    assert len(out) == 1
    assert 'if (M2C_FIELD(p, f32 *, 4) < 1.5f) goto decomp_float_store;' in out[0][1]
    assert 'decomp_float_store: M2C_FIELD(p, u8 *, 8) = 0U;' in out[0][1]


def test_rejects_changed_stores_and_unproved_macro_or_branch():
    assert not repair.variants(SOURCE, 'f', ASM)
    assert not repair.variants(SOURCE, 'f', ASM.replace('bc1tl', 'bc1t'), HEADER)
    assert not repair.variants(SOURCE.replace('= 0U;', '= 1U;', 1), 'f', ASM, HEADER)
    assert not repair.variants(SOURCE.replace('-M2C_FIELD', '-M2C_FIELD', 1).replace('< 1.5f', '< 2.5f', 1), 'f', ASM, HEADER)

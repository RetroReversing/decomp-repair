from decomprepair import inline_reused_float_expression as repair

HEADER = '#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))'
SOURCE = '''void f(char *p, int mode) {
    f32 temp;
    if (mode) {
        temp = M2C_FIELD(p, f32 *, 4) * 2.0f;
        M2C_FIELD(p, f32 *, 8) = temp + 1.0f;
    } else {
        temp = M2C_FIELD(p, f32 *, 12) * 2.0f;
        M2C_FIELD(p, f32 *, 16) = temp + 1.0f;
    }
}
'''


def test_each_adjacent_pair_can_be_inlined_independently():
    out = repair.variants(SOURCE, 'f', HEADER)
    assert len(out) == 2
    assert '((f32) (M2C_FIELD(p, f32 *, 4) * 2.0f))' in out[0][1]
    assert 'temp = M2C_FIELD(p, f32 *, 12)' in out[0][1]


def test_rejects_extra_uses_side_effects_and_unknown_macro():
    assert not repair.variants(SOURCE.replace('    if (mode)', '    consume(temp);\n    if (mode)'), 'f', HEADER)
    assert not repair.variants(SOURCE.replace('M2C_FIELD(p, f32 *, 4) * 2.0f', 'change()'), 'f', HEADER)
    assert not repair.variants(SOURCE, 'f')

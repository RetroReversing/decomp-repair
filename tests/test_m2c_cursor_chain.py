from decomprepair import m2c_cursor_chain

DRAFT = """void f(void) {
    s32 *var_a2;
    s32 a;
    s32 b;
    s32 c;
    s32 d;
    void *temp_a2;
    void *temp_a2_2;

    var_a2 = &D_80100000;
    do {
        a = M2C_FIELD(var_a2, s32 *, 0);
        temp_a2 = var_a2 + 4;
        b = M2C_FIELD(var_a2, s32 *, 4);
        temp_a2_2 = temp_a2 + 4;
        c = M2C_FIELD(temp_a2, s32 *, 4);
        d = M2C_FIELD(temp_a2_2, s32 *, 4);
        var_a2 = temp_a2_2 + 4 + 4;
        g(a, b, c, d);
    } while (var_a2 != &D_80100100);
}
"""


def test_the_chain_becomes_post_increments():
    out = m2c_cursor_chain.variants(DRAFT, 'f')
    assert [family for family, _ in out] == ['m2c_cursor_chain']
    text = out[0][1]
    assert 'a = *var_a2++;\n        b = *var_a2++;\n        c = *var_a2++;\n        d = *var_a2++;\n        g(' in text
    assert 'temp_a2 + 4' not in text


def test_a_step_that_does_not_cover_the_reads_is_left_alone():
    assert not m2c_cursor_chain.variants(DRAFT.replace('temp_a2_2 + 4 + 4', 'temp_a2_2 + 4'), 'f')
    assert not m2c_cursor_chain.variants(DRAFT.replace('g(a, b, c, d);', 'g(a, b, c, temp_a2);'), 'f')

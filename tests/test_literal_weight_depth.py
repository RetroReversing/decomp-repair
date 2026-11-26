from decomprepair.literal_weight_depth import FAMILY, variants

SOURCE = """void tick(u8 *arg0, s32 arg1) {
    s32 i;
    u8 *p;

    for (i = 0; i < 7; i++) {
        p = arg0 + i * 16;
        if (arg1 != 0) {
            *(f32 *)(p + 4) = (1.0f - *(f32 *)(p + 4)) * *(f32 *)(p + 8) + *(f32 *)(p + 4);
        }
        *(f32 *)(p + 12) = 0.0f;
    }
    *(f32 *)(arg0 + 4) = 2.0f;
}
"""


def test_wraps_the_nested_literal_statement_twice_and_three_times():
    children = variants(SOURCE, 'tick')
    assert [family for family, _ in children] == [FAMILY, FAMILY]
    assert 'do { do { *(f32 *)(p + 4) = (1.0f - ' in children[0][1]
    assert 'do { do { do { *(f32 *)(p + 4) = (1.0f - ' in children[1][1]
    # the zero literal and the statement outside the loop are left alone
    assert all('do { do { *(f32 *)(p + 12)' not in text and 'do { do { *(f32 *)(arg0' not in text for _, text in children)


def test_no_loop_no_children():
    assert variants("void f(f32 *p) { f32 x; x = 2.0f; *p = x; }", 'f') == []

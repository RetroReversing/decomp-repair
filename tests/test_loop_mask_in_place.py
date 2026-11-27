from decomprepair import loop_mask_in_place

DRAFT = """void f(s32 *table) {
    s32 key;
    s32 v;
    s32 size;
    s32 *p;

    key = g();
    p = table;
    size = 0x1000;
    for (;;) {
        v = *p;
        if (v != (key & 0x01FFE000)) {
            p++;
            size *= 4;
            continue;
        }
        break;
    }
    h(size);
}
"""


def test_the_mask_moves_ahead_of_the_loop():
    out = loop_mask_in_place.variants(DRAFT, 'f')
    assert len(out) == 2
    assert 'key &= 0x01FFE000;\n    p = table;\n    size = 0x1000;\n    for (;;) {' in out[0][1]
    assert 'size = 0x1000;\n    key &= 0x01FFE000;\n    for (;;) {' in out[1][1]
    assert all('if (v != key) {' in text for _, text in out)


def test_a_value_read_elsewhere_is_left_alone():
    assert not loop_mask_in_place.variants(DRAFT.replace('h(size);', 'h(key);'), 'f')

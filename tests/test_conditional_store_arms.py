from decomprepair import conditional_store_arms_repairs as repairs

SOURCE = '''void f(u8 *p, u8 *out) {
    u8 t;
    s32 c;
    c = p[0];
    if (p[1] == 0xDE) {
        t = c - 0x3A;
        if (c >= 0xCA) { t = c - 0x3F; }
        goto shared;
    }
    if (p[1] == 0xDF) {
        t = c - 0x3A;
shared:
        *out = t;
        p += 1;
    } else {
        *out = c;
    }
    *p = 0;
}
'''


def test_both_stores_written_and_goto_inlined_in_one_child():
    family, text = repairs.variants(SOURCE, 'f')[0]
    assert family == repairs.FAMILY
    assert 'goto' not in text and 'shared:' not in text
    assert 'if (c >= 0xCA) { *out = c - 0x3F; } else { *out = c - 0x3A; }' in text
    assert 'else if (p[1] == 0xDF)' in text
    assert '*out = t;' not in text


def test_temporary_read_later_is_kept():
    source = '''void f(u8 *out, s32 c) {
    u8 t;
    t = c - 1;
    *out = t;
    out[1] = t;
}
'''
    assert repairs.variants(source, 'f') == []


def test_call_is_not_made_conditional():
    source = '''void f(u8 *out, s32 c) {
    u8 t;
    t = g(c);
    if (c) { t = 2; }
    *out = t;
}
'''
    assert repairs.variants(source, 'f') == []


def test_narrow_temporary_keeps_its_cast_for_a_wider_store():
    source = '''void f(s32 *out, s32 c) {
    u8 t;
    t = c + 1;
    *out = t;
}
'''
    assert repairs.variants(source, 'f')[0][1].count('*out = (u8) (c + 1);') == 1

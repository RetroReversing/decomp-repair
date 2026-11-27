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


TESTED = '''void f(u8 *p) {
    s32 t;
    f2(p);
    t = f3(p);
    if (t == 0) {
        t = 0x3000;
    }
    *(s32 *)(p + 0x3C) = t;
    *(s32 *)(p + 0x44) = *(s32 *)(p + 0x3C) / 44;
}
'''


def test_a_defaulted_temporary_the_test_reads_stores_in_each_arm():
    [(family, text)] = repairs.variants(TESTED, 'f')
    assert family == repairs.TESTED_FAMILY
    assert ('t = f3(p);\n    if (t == 0) { *(s32 *)(p + 0x3C) = 0x3000; } '
            'else { *(s32 *)(p + 0x3C) = t; }\n') in text


def test_the_stores_cast_is_kept_in_both_arms():
    source = TESTED.replace('= t;\n    *(s32', '= (u16) t;\n    *(s32')
    [(_, text)] = repairs.variants(source, 'f')
    assert '= (u16) 0x3000; } else { *(s32 *)(p + 0x3C) = (u16) t; }' in text


def test_a_temporary_read_later_is_left_alone():
    source = TESTED.replace('/ 44;', '/ t;')
    assert repairs.variants(source, 'f') == []


def test_a_default_computed_by_a_call_is_left_alone():
    assert repairs.variants(TESTED.replace('t = 0x3000;', 't = f4();'), 'f') == []


DRAFT = '''void f(void *arg0, void *other) {
    s16 var_v0;
    s16 var_v0_2;

    var_v0 = 0x2AF8;
    if (M2C_FIELD(arg0, u8 *, 0x6E) == 0) {
        var_v0 = -0x3A98;
    }
    M2C_FIELD(arg0, s16 *, 0) = var_v0;
    M2C_FIELD(arg0, s16 *, 2) = -0x1F40;
    M2C_FIELD(arg0, u8 *, 0x75) = 9U;
    var_v0_2 = 0x1F4;
    if (M2C_FIELD(arg0, u8 *, 0x6E) == 0) {
        var_v0_2 = 0x28;
    }
    M2C_FIELD(other, s16 *, 0) = var_v0_2;
    M2C_FIELD(other, s16 *, 2) = 0x20;
    M2C_FIELD(other, u8 *, 0x78) = 2;
    M2C_FIELD(other, u8 *, 0x73) = 0;
    M2C_FIELD(other, s32 *, 0x80) = 0x408;
}
'''


def test_a_field_macro_store_is_not_a_call():
    family, text = repairs.variants(DRAFT, 'f')[0]
    assert family == repairs.FAMILY
    assert 'var_v0 = 0x2AF8;' not in text and 'var_v0_2 = 0x1F4;' not in text
    assert 'else { M2C_FIELD(arg0, s16 *, 0) = (s16) (0x2AF8); }' in text


def test_short_literal_store_run_goes_into_both_arms():
    runs = [text for family, text in repairs.variants(DRAFT, 'f') if family == repairs.RUN_FAMILY]
    short = runs[0]
    tail = 'M2C_FIELD(arg0, s16 *, 2) = -0x1F40; M2C_FIELD(arg0, u8 *, 0x75) = 9U; }'
    assert short.count(tail) == 2
    # the second site's run is longer than the limit, so it keeps its one store
    assert short.count('M2C_FIELD(other, s16 *, 2) = 0x20;') == 1
    assert any(text.count('M2C_FIELD(other, s16 *, 2) = 0x20;') == 2 for text in runs[1:])


def test_run_stops_at_a_store_that_is_not_a_literal():
    source = DRAFT.replace('M2C_FIELD(arg0, s16 *, 2) = -0x1F40;', 'M2C_FIELD(arg0, s16 *, 2) = g(arg0);')
    runs = [text for family, text in repairs.variants(source, 'f') if family == repairs.RUN_FAMILY]
    assert all('g(arg0); M2C_FIELD' not in text for text in runs)
    assert all(text.count('g(arg0)') == 1 for text in runs)

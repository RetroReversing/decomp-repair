from decomprepair import register_reuse_repairs as reuse


def copies(source):
    return [text for family, text in reuse.variants(source, 'f') if family == 'copy_register_reuse']


def test_a_copy_inside_an_arm_is_not_reused_after_the_arm():
    source = '''s32 f(s32 arg0) {
    s32 value;
    s32 result;

    result = g();
    if (arg0 != 0) {
        value = 2;
        result = value;
    }
    return result;
}
'''
    assert not any('return value;' in text for text in copies(source))


def test_a_copy_is_not_reused_past_a_label():
    source = '''s32 f(s32 arg0) {
    s32 value;
    s32 result;

    value = g();
    if (arg0 != 0) {
        goto done;
    }
    result = value;
done:
    return result;
}
'''
    assert not any('return value;' in text for text in copies(source))


def test_a_copy_is_still_reused_in_its_block():
    source = '''s32 f(void) {
    s32 value;
    s32 result;

    value = g();
    result = value;
    if (h()) {
        use(result);
    }
    return result;
}
'''
    assert any('use(value);' in text and 'return value;' in text for text in copies(source))

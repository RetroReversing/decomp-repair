from decomprepair import flag_temp_inline as inline

SOURCE = '''void f(void *p, s32 n) {
    u32 flags;
    s32 fast;
    s32 slow;
    s32 hit;

    flags = *(u8 *)p;
    fast = flags & 4;
    slow = flags & 8;
    if (n > 0) {
        fast = flags & 4;
        hit = 1;
    }
    if (fast != 0) {
        use(hit);
    }
    if ((slow != 0) && (n == 3)) {
        use(slow);
    }
}
'''


def test_each_temporary_is_a_child_and_all_of_them_one_more():
    out = [text for _, text in inline.variants(SOURCE, 'f')]
    assert len(out) == 3
    assert 'fast' not in out[0] and 'slow = flags & 8;' in out[0]
    assert 'if ((flags & 4) != 0) {' in out[0]
    assert 'slow' not in out[1] and 'if (((flags & 8) != 0) && (n == 3)) {' in out[1]
    assert 'use((flags & 8));' in out[1]
    both = out[2]
    assert 'fast' not in both and 'slow' not in both
    assert 'flags = *(u8 *)p;' in both and both.count('{') == both.count('}')


def test_a_flag_word_assigned_again_or_a_temporary_with_other_values_is_left_alone():
    assert not inline.variants(SOURCE.replace('        hit = 1;', '        flags = 0;\n        hit = 1;'), 'f')
    other = SOURCE.replace('fast = flags & 4;\n        hit', 'fast = flags & 2;\n        hit')
    assert all('fast = flags & 2;' in text for _, text in inline.variants(other, 'f'))
    early = SOURCE.replace('    fast = flags & 4;\n    slow', '    use(fast);\n    slow')
    assert all('use(fast);' in text and 'fast != 0' in text for _, text in inline.variants(early, 'f'))


def test_the_module_declares_itself_to_the_registry():
    from decomprepair import registry
    declared = {r.module: r for r in registry.declared()}
    assert 'flag_temp_inline' in declared and not registry.problems(declared['flag_temp_inline'])

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


JOINED = '''void f(s32 bits, u8 left, u8 right) {
    s32 hit;
    s32 var_v0;

    hit = 0;
    if (bits & 1) {
        hit = 1;
    }
    if (bits & 2) {
        if (left != right) {
            hit = 1;
            goto done;
        }
        var_v0 = hit & 0xFF;
        if (right < 5) {
            hit = 1;
            goto done;
        }
    } else {
done:
        var_v0 = hit & 0xFF;
    }
    if (var_v0 != 0) {
        use(hit);
    }
}
'''


def test_a_word_assigned_several_times_when_every_path_to_the_read_sets_the_temporary_after_it():
    out = [text for _, text in inline.variants(JOINED, 'f')]
    assert len(out) == 1
    assert 'var_v0' not in out[0] and 'if ((hit & 0xFF) != 0) {' in out[0]
    assert 'done:\n;\n    }' in out[0]


def test_a_write_of_the_word_between_the_temporary_and_the_read_is_refused():
    late = JOINED.replace('        if (right < 5) {', '        hit = 2;\n        if (right < 5) {')
    assert not inline.variants(late, 'f')
    unset = JOINED.replace('done:\n        var_v0 = hit & 0xFF;', 'done:\n        use(0);')
    assert not inline.variants(unset, 'f')
    shared = JOINED.replace('s32 hit;', 'extern s32 hit;')
    assert not inline.variants(shared.replace('    hit = 0;\n', '    hit = 0;\n    watch(&hit);\n'), 'f')


def test_the_module_declares_itself_to_the_registry():
    from decomprepair import registry
    declared = {r.module: r for r in registry.declared()}
    assert 'flag_temp_inline' in declared and not registry.problems(declared['flag_temp_inline'])

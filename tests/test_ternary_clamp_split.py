from decomprepair import ternary_clamp_split as repair

SOURCE = '''void f(s32 *p) {
    s32 count, index, next;

    count = p[1];
    next = index + 1;
    next = next < count ? next : 0;
    g(p, index, next);
    if (p[0]) {
        h(next, count);
        return;
    }
    h(index, next);
}
'''


def test_the_clamp_becomes_a_copy_and_a_guarded_default():
    (family, out), = repair.variants(SOURCE, 'f')
    assert family == 'ternary_clamp_split'
    assert '    s32 next_clamped;\n' in out
    assert '    next_clamped = next;\n    if (next >= count) {\n        next_clamped = 0;\n    }\n' in out
    assert 'g(p, index, next_clamped);' in out and 'h(next_clamped, count);' in out and 'h(index, next_clamped);' in out
    assert 'next < count ?' not in out


def test_the_other_arm_order_is_guarded_by_the_test_itself():
    (_, out), = repair.variants(SOURCE.replace('next < count ? next : 0', 'next >= count ? 0 : next'), 'f')
    assert 'if (next >= count) {\n        next_clamped = 0;' in out


def test_declines_when_the_variable_is_written_again_or_unused_after():
    assert repair.variants(SOURCE.replace('    h(index, next);', '    next = 1;\n    h(index, next);'), 'f') == []
    assert repair.variants(SOURCE.replace('g(p, index, next);', 'g(p, index, 1);').replace('h(next, count);', 'h(1, count);')
                           .replace('h(index, next);', 'h(index, 1);'), 'f') == []


def test_declines_inside_a_branch_a_float_or_a_call_in_the_test():
    nested = SOURCE.replace('    next = next < count ? next : 0;\n', '    if (p[2]) {\n        next = next < count ? next : 0;\n    }\n')
    assert repair.variants(nested, 'f') == []
    assert repair.variants(SOURCE.replace('s32 count, index, next;', 's32 count, index;\n    f32 next;'), 'f') == []
    assert repair.variants(SOURCE.replace('next < count ?', 'next < k(count) ?'), 'f') == []

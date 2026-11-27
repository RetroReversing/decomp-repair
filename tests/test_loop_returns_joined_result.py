from decomprepair.loop_returns_joined_result import FAMILY, variants

SOURCE = '''s32 g();
s32 h();
extern s8 D_1;

s32 f(s32 arg0) {
    u8 sp10;

    D_1 = 0;
    for (;;) {
        g(&sp10);
        if (sp10 == arg0) {
            D_1 = 1;
            return 0;
        }
        if (h(sp10)) {
            return g(sp10);
        }
    }
}
'''


def children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_every_exit_goes_through_one_result_local():
    zero, bare, start = children()
    assert 'ret = 0; goto done;' in zero and 's32 ret = 0;' in zero
    assert 'ret = g(sp10); goto done;' in zero
    assert zero.rstrip().endswith('done:\n    return ret;\n}')
    assert 's32 ret;' in bare


def test_the_exit_that_returns_the_start_value_just_leaves():
    *_, start = children()
    assert 's32 ret = 0;' in start and 'D_1 = 1;\n            goto done;' in start
    assert 'ret = 0; goto' not in start


def test_a_copy_fence_around_the_call_goes():
    fenced = SOURCE.replace('        if (h(sp10)) {\n            return g(sp10);\n        }\n',
                            '        a = sp10;\n        do { c = a;\n if (h(sp10)) {\n            return g(c);\n        } } while (0);\n'
                            ).replace('    u8 sp10;\n', '    u8 sp10;\n    u8 a;\n    s32 c;\n')
    zero, *_ = children(fenced)
    assert 'ret = g(sp10); goto done;' in zero and 'while (0)' not in zero


def test_void_functions_and_braceless_exits_are_left_alone():
    assert not children(SOURCE.replace('s32 f(', 'void f(').replace('return 0;', 'return;'))
    assert not children(SOURCE.replace('        if (h(sp10)) {\n            return g(sp10);\n        }\n',
                                       '        if (h(sp10)) return g(sp10);\n'))
    assert not children(SOURCE.replace('for (;;)', 'if (1)'))

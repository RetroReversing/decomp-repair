from decomprepair.disjoint_local_merge_repairs import FAMILY, variants

SOURCE = '''void f(s32 n)
{
    s32 var_s7;
    s32 var_s7_3;
    s32 other;
    var_s7 = 0;
    do {
        step(var_s7);
        var_s7 += 1;
    } while (var_s7 < n);
    var_s7_3 = 0;
    do {
        more(var_s7_3);
        var_s7_3 += 1;
    } while (var_s7_3 < n);
}
'''


def merged(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_later_counter_takes_the_earlier_name():
    first = merged()[0]
    assert 'var_s7_3' not in first
    assert 'var_s7 = 0;\n    do {\n        more(var_s7);' in first
    assert first.count('var_s7 += 1;') == 2


def test_a_counter_still_read_after_the_second_loop_is_not_renamed():
    texts = merged(SOURCE.replace('} while (var_s7_3 < n);\n}', '} while (var_s7_3 < n);\n    last(var_s7);\n}'))
    assert not [t for t in texts if 'var_s7_3' not in t]


def test_loops_that_share_a_nest_are_not_merged():
    nested = '''void f(s32 n)
{
    s32 a;
    s32 b;
    a = 0;
    do {
        b = 0;
        do {
            step(a, b);
            b += 1;
        } while (b < n);
        a += 1;
    } while (a < n);
}
'''
    assert not merged(nested)

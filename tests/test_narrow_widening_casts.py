"""A narrow local widened to `s32` keeps its value through casts at its reads."""
from decomprepair import narrow_widening_repairs as n

SOURCE = '''void f(void) {
    u16 ret;

    ret = g();
    if ((u16) (ret + 2) < 2) return;
    table[ret].a = 1;
}
'''


def test_widened_with_casts_at_the_other_reads():
    children = [out for _, out in n.variants(SOURCE, 'f')]
    assert any('s32 ret;' in c and '(u16) (ret + 2)' in c and 'table[((u16) ret)].a' in c for c in children)


def test_a_stepped_local_is_only_widened():
    children = [out for _, out in n.variants(SOURCE.replace('ret = g();', 'ret = g();\n    ret++;'), 'f')]
    assert not any('((u16) ret)' in c for c in children)

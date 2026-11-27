"""A variable filled by both arms of an `if`/`else`, written as a conditional expression."""
from decomprepair import branch_choice_ternary as x
from decomprepair import registry

SOURCE = '''void f(void *arg0) {
    s32 t;
    s32 d;

    t = *(u16 *)((s8 *)arg0 + 0xCA) & 0xFFF;
    if (t >= 0) {
        d = t;
    } else {
        d = -t;
    }
    if (d >= 0x3E9) {
        *(s16 *)((s8 *)arg0 + 0xCA) = 0;
    }
    t = *(u16 *)((s8 *)arg0 + 0xCC) & 0xFFF;
    if (t >= 0) {
        d = t;
    } else {
        d = -t;
    }
    if (d >= 0x3E9) {
        *(s16 *)((s8 *)arg0 + 0xCC) = 0;
    }
}
'''


def children():
    return [child for family, child in x.variants(SOURCE, 'f')]


def test_both_absolute_values_become_conditional_expressions_in_one_child():
    first = children()[0]
    assert first.count('d = (t >= 0) ? t : -t;') == 2
    assert 'else' not in first


def test_each_site_alone_and_inverted():
    kids = children()
    assert sum(k.count('d = (t >= 0) ? t : -t;') == 1 for k in kids) >= 2
    assert any('d = (t < 0) ? -t : t;' in k for k in kids)


def test_an_else_if_chain_and_two_variables_are_left_alone():
    chain = SOURCE.replace('''    } else {
        d = -t;
    }
    if (d >= 0x3E9) {
        *(s16 *)((s8 *)arg0 + 0xCA) = 0;
    }''', '''    } else {
        d = -t;
    } else if (t) {
        d = 1;
    }''', 1)
    assert all(k.count('?') <= 1 for family, k in x.variants(chain, 'f'))
    other = '''void f(s32 t) {
    s32 d, e;
    if (t) {
        d = 1;
    } else {
        e = 2;
    }
}
'''
    assert x.variants(other, 'f') == []


def test_declared():
    assert registry.get('branch_choice_ternary').families == (x.FAMILY,)

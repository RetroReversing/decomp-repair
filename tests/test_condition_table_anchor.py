"""A two-flag truth table: first flag first, and the rows the author left out as empty tests."""
from decomprepair import condition_table_anchor as table

SOURCE = '''s32 f(void *x, void *y) {
    s8 c1;
    s8 c2;
    c1 = g(x);
    c2 = g(y);
    if ((c2 == 0) & (c1 != 0))
    {
        return 1;
    }
    if ((c2 != 0) & ((unsigned) (c1 == 0)))
    {
        return 2;
    }
    return 0;
}
'''


def _by(family, source=SOURCE):
    return [text for name, text in table.variants(source, 'f') if name == family]


def test_the_table_is_rewritten_with_each_flag_first():
    out = _by('condition_table_order')
    assert any('if ((c1 != 0) & (c2 == 0))' in t and 'if (((unsigned) (c1 == 0)) & (c2 != 0))' in t for t in out)
    assert any('if ((c2 == 0) & (c1 != 0))' in t for t in out) or len(out) >= 1


def test_each_missing_row_is_an_empty_test_before_the_table():
    out = _by('condition_table_anchor')
    first = [t for t in out if 'if ((c1 == 0) & (c2 == 0))\n    {\n    }\n    if ((c1 != 0) & (c2 == 0))' in t]
    assert first, out
    assert any(t.count('{\n    }') == 2 for t in out)  # both missing rows together
    assert all(t.index('c2 = g(y);') < t.index('{\n    }') for t in out)


def test_a_complete_table_gets_no_anchor():
    full = '''void f(s8 a, s8 b) {
    if ((a == 0) & (b == 0)) { g(1); }
    if ((a == 0) & (b != 0)) { g(2); }
    if ((a != 0) & (b == 0)) { g(3); }
    if ((a != 0) & (b != 0)) { g(4); }
}
'''
    assert not _by('condition_table_anchor', full)


def test_tests_with_an_else_or_a_single_test_are_left_alone():
    single = 'void f(s8 a, s8 b) {\n    if ((a == 0) & (b == 0)) { g(1); }\n}\n'
    assert not table.variants(single, 'f')
    other = 'void f(s8 a, s8 b) {\n    if ((a == 0) & (b == 0)) { g(1); } else { g(2); }\n    if ((a != 0) & (b == 0)) { g(3); }\n}\n'
    assert not table.variants(other, 'f')

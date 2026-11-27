"""else_chain_compare_zero: the later arms of a chain compare with zero."""
from decomprepair import else_chain_compare_zero as c
from decomprepair import registry

DRAFT = '''void f(int idx)
{
    if (mode == 4) {
        a(idx);
    } else if (mode == 1) {
        a(idx);
    } else if (flag == 0) {
        b();
    }
    if (sel == 0) {
        c();
    } else if (sel == 1) {
        d();
    }
    if (other[idx].kind == 4) {
        a(idx);
    } else if (other[idx].kind == 1) {
        a(idx);
    }
}
'''


def test_all_later_arms_together_first_and_a_chain_that_tests_zero_is_left_alone():
    out = c.variants(DRAFT, 'f')
    assert [family for family, _ in out] == ['else_chain_compare_zero'] * 3
    both = out[0][1]
    assert 'else if (mode == 0)' in both and 'else if (other[idx].kind == 0)' in both
    assert 'else if (sel == 1)' in both
    assert 'else if (other[idx].kind == 1)' in out[1][1] and 'else if (mode == 0)' in out[1][1]


def test_a_chain_on_different_values_has_no_sites():
    source = 'void f(void) { if (a == 4) { g(); } else if (b == 1) { g(); } }\n'
    assert c.variants(source, 'f') == []


def test_the_registry_declares_it():
    assert any(repair.module == 'else_chain_compare_zero' for repair in registry.declared())

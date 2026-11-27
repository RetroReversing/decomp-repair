from decomprepair import branch_polarity_repairs, conjunct_reguard

SOURCE = """void f(Obj *obj, s16 v)
{
    if (obj->speed < 1.0f && v < 0) {
        switch (v) {
        case -2:
            a();
            break;
        case -1:
            b();
            break;
        }
    } else if (v >= 0 && !(obj->speed < 10.0f)) {
        c();
    } else if (v != -1) {
        d();
    }
}
"""


def test_the_last_conjunct_guards_the_switch():
    children = [child for _, child in conjunct_reguard.variants(SOURCE, 'f')]
    assert len(children) == 1 and 'if (v < 0) switch (v)' in children[0]


def test_no_guard_without_a_conjunct():
    assert conjunct_reguard.variants(SOURCE.replace('obj->speed < 1.0f && ', ''), 'f') == []


def test_an_else_if_arm_swaps_with_the_arm_before_it():
    children = [child for _, child in branch_polarity_repairs.variants(SOURCE, 'f')]
    assert any('if (!(v >= 0 && !(obj->speed < 10.0f))) {' in child and child.index('d();') < child.index('c();')
               for child in children)

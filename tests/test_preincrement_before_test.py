from decomprepair import registry
from decomprepair.preincrement_before_test import FAMILY, variants

SOURCE = """void scan(Node *node) {
    u16 k;
    k = 0;
    while (node->life != 0) {
        node++;
        if (++k >= 501) {
            break;
        }
    }
    use(k);
}
"""


def _children(source=SOURCE):
    return [child for family, child in variants(source, 'scan') if family == FAMILY]


def _with(condition):
    return SOURCE.replace('++k >= 501', condition)


def test_the_step_goes_on_its_own_line_before_the_test():
    assert _children() == [SOURCE.replace('        if (++k >= 501) {', '        k++;\n        if (k >= 501) {')]


def test_decrements_compound_steps_members_and_the_mirrored_side():
    assert 'k--;\n        if (k == 0) {' in _children(_with('--k == 0'))[0]
    assert 'k += 4;\n        if (k > 501) {' in _children(_with('(k += 4) > 501'))[0]
    assert 'k++;\n        if (501 <= k) {' in _children(_with('501 <= ++k'))[0]
    assert 'k -= 2;\n        if (limit != k) {' in _children(_with('limit != (k -= 2)'))[0]
    assert 'node->count++;\n        if (node->count >= 3) {' in _children(_with('++node->count >= 3'))[0]
    assert 'k++;\n        if ((k & 3) == 0 && ready(k)) {' in _children(_with('(++k & 3) == 0 && ready(k)'))[0]


def test_two_sites_are_offered_together_and_one_at_a_time():
    source = SOURCE.replace('    use(k);', '    if (--k) {\n        use(k);\n    }')
    children = _children(source)
    assert len(children) == 3
    assert 'k++;' in children[0] and 'k--;' in children[0]


def test_a_step_that_may_not_run_or_is_not_first_is_left_alone():
    assert _children(_with('ready && ++k >= 501')) == []
    assert _children(_with('check() < ++k')) == []
    assert _children(_with('(u8) ++k >= 5')) == []
    assert _children(_with('++k >= k')) == []
    assert _children(_with('k < ++k')) == []
    assert _children(_with('++table[next()] >= 5')) == []
    assert _children(SOURCE.replace('        if (++k >= 501) {', '        if (k) {\n        } else if (++k >= 501) {')) == []
    assert _children(SOURCE.replace('u16 k;', 'volatile u16 k;')) == []


def test_it_is_declared():
    assert any(FAMILY in repair.families for repair in registry.declared())

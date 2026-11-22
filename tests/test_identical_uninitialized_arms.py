from decomprepair.branch_layout_repairs import scalar_tails

SOURCE = """
int f(void) {
    float scratch;
    if (scratch) {
        setup();
    } else {
        setup();
    }
    return 0;
}
"""


def test_removes_uninitialized_test_and_preserves_selected_block():
    [(family, candidate)] = scalar_tails(SOURCE, 'f')
    assert family == 'common_scalar_tail'
    assert 'if (scratch)' not in candidate
    assert candidate.count('setup();') == 1
    assert candidate.count('\n') == SOURCE.count('\n')


def test_leaves_different_arms_and_qualified_or_initialized_conditions():
    assert not scalar_tails(SOURCE.replace('setup();', 'setup_other();', 1), 'f')
    assert not scalar_tails(SOURCE.replace('float scratch;', 'volatile float scratch;'), 'f')
    assert not scalar_tails(SOURCE.replace('float scratch;', 'float scratch = 0;'), 'f')
    assert not scalar_tails(SOURCE.replace('float scratch;', '{ float scratch; }'), 'f')
    text = SOURCE.replace('setup();', 'setup("a  b");', 1).replace('setup();', 'setup("a b");')
    assert not scalar_tails(text, 'f')

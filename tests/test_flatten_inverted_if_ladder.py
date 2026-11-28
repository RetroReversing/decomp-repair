from decomprepair.flatten_inverted_if_ladder import variants

SOURCE = '''void f(int x) {
    if (x != 5) {
        if (x != 0) { error(); break; }
        else { clear(); break; }
    } else { found(); }
    next();
}
'''


def test_flatten_preserves_conditions_and_all_arm_bodies():
    result = variants(SOURCE, 'f')[0][1]
    assert 'if (x == 5) { found(); } else if (x != 0) { error(); break; } else { clear(); break; }' in result
    assert result.count('next();') == 1


def test_rejects_extra_outer_statements_or_labels_and_macros():
    assert not variants(SOURCE.replace('if (x != 0)', 'side(); if (x != 0)'), 'f')
    assert not variants(SOURCE.replace('clear();', 'label: clear();'), 'f')
    assert not variants(SOURCE, 'f', '#define error() other()')

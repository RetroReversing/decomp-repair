"""A loop-note wrapper moved from one statement to a point after a later one."""
from decomprepair.wrapper_boundary_shift import FAMILY, FAMILY_GUARD, variants

SAVED = '''void f(void)
{
    u16 i;
    do { h[i] = y + 0x20; } while (0);
    g[0][i] = q;
    if (n > 0) {
        for (k = 0; k < n; k++) { z(); }
    }
}
'''


def _children(source, family=FAMILY):
    return [src for fam, src in variants(source, 'f') if fam == family]


def test_the_wrapper_comes_off_and_an_empty_one_follows_the_next_statement():
    out = _children(SAVED)
    assert len(out) == 1  # the statement after g[0][i] = q is an `if`: no second distance
    child = out[0]
    assert '    h[i] = y + 0x20;\n    g[0][i] = q;\n    do { } while (0);\n    if (n > 0) {' in child
    assert 'do { h[i]' not in child


def test_two_following_simple_statements_give_a_second_child():
    source = SAVED.replace('    if (n > 0) {', '    w = 1;\n    if (n > 0) {')
    out = _children(source)
    assert len(out) == 2
    assert out[1].count('do { } while (0);') == 1 and out[1].index('w = 1;') < out[1].index('do { } while (0);')


def test_a_nested_wrapper_loses_one_layer_only():
    source = SAVED.replace('do { h[i] = y + 0x20; } while (0);', 'do { do { h[i] = y + 0x20; } while (0); } while (0);')
    assert '    do { h[i] = y + 0x20; } while (0);\n    g[0][i] = q;\n    do { } while (0);' in _children(source)[0]


def test_a_statement_without_a_wrapper_or_without_a_simple_neighbour_gives_nothing():
    assert variants(SAVED.replace('do { h[i] = y + 0x20; } while (0);', 'h[i] = y + 0x20;'), 'f') == []
    assert variants(SAVED.replace('    g[0][i] = q;\n', '    if (q) { g[0][i] = q; }\n'), 'f') == []


def test_the_redundant_entry_guard_of_the_next_loop_is_dropped_in_a_child_of_its_own():
    out = _children(SAVED, FAMILY_GUARD)
    assert len(out) == 1
    assert '    do { } while (0);\n    for (k = 0; k < n; k++) { z(); }\n}' in out[0]
    assert 'if (n > 0)' not in out[0]

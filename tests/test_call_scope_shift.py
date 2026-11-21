from decomprepair import call_scope_repairs as scope

SOURCE = '''extern u8 D_1[];
void f(void) {
    g(10);
    do { h(D_1[0]); } while (0);
    k();
}
'''


def test_existing_wrapper_moves_to_each_neighbouring_call():
    out = [text for family, text in scope.variants(SOURCE, 'f') if family == scope.SHIFT]
    assert len(out) == 2
    assert any('do { g(10); } while (0);' in t and '    h(D_1[0]);' in t and 'do { h' not in t for t in out)
    assert any('do { k(); } while (0);' in t and 'do { h' not in t for t in out)
    assert all(t.count('while (0)') == 1 for t in out)


def test_no_shift_without_a_wrapper_or_onto_another_wrapper():
    plain = SOURCE.replace('do { h(D_1[0]); } while (0);', 'h(D_1[0]);')
    assert not [t for family, t in scope.variants(plain, 'f') if family == scope.SHIFT]
    both = SOURCE.replace('g(10);', 'do { g(10); } while (0);')
    out = [t for family, t in scope.variants(both, 'f') if family == scope.SHIFT]
    assert all('do { g(10); } while (0);' in t for t in out)

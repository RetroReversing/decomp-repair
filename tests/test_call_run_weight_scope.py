from decomprepair.call_run_weight_scope import variants

SOURCE = '''void f(int x) {
    if (x) {
        print(1, x);
        print(2, x);
        print(3, x);
        print(4, x);
    }
}
'''


def test_wraps_the_complete_run_at_all_supported_depths():
    children = variants(SOURCE, 'f')
    assert [child.count('do {') for _, child in children] == [1, 4, 8, 12, 15]
    for _, child in children:
        assert child.count('print(') == 4
        assert child.index('do {') < child.index('print(1')
        assert child.index('} while (0);') > child.index('print(4')


def test_rejects_macro_or_control_flow_runs():
    assert variants(SOURCE, 'f', '#define print(x,y) do { if (x) break; } while (0)') == []
    assert variants(SOURCE.replace('print(2, x);', 'continue;'), 'f') == []
    assert variants(SOURCE.replace('print(2, x);', 'print(2, __LINE__);'), 'f') == []
    assert variants(SOURCE.replace('print(2, x);', 'other(2, x);'), 'f') == []

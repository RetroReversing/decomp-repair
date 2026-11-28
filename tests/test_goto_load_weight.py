from decomprepair.goto_load_weight import variants

SOURCE = '''
void f(int n) {
    int x;
    int i;
loop: {
    x = *(table + i);
    use(x);
}
    if (n--) goto loop;
}
'''


def test_offers_each_weight_for_real_load():
    children = variants(SOURCE, 'f')
    assert len(children) == 3
    assert 'do { do { do { do { x = *(table + i); } while (0); } while (0); } while (0); } while (0);' in children[-1][1]


def test_unbraced_or_labeled_load_is_not_wrapped():
    assert variants(SOURCE.replace('    x =', '    if (n)\n    x ='), 'f') == []
    assert variants(SOURCE.replace('    x =', 'other:\n    x ='), 'f') == []


def test_requires_backward_loop_and_plain_load():
    assert variants(SOURCE.replace('goto loop;', 'return;'), 'f') == []
    assert variants(SOURCE.replace('*(table + i)', '*(table + i++)'), 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define i other', '#define while(x)'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []
    assert variants(SOURCE.replace('    x =', '#if FOO\n    x =').replace('    use(x);', '#endif\n    use(x);'), 'f') == []

from decomprepair.scoped_slot_base import variants

SOURCE = '''
extern char table[];
void f(int idx) {
    char *p;
    if (idx) {
        p = (idx * 4) + table;
    } else {
    label:
        p = (idx * 4) + table;
    }
    use(p);
}
'''


def test_offers_each_and_both_scoped_bases():
    children = variants(SOURCE, 'f')
    assert len(children) == 3
    text = children[-1][1]
    assert text.count('__typeof__(table + 0) __repair_site_base;') == 2
    assert text.count('p = __repair_site_base + (idx * 4);') == 2


def test_rejects_shadow_volatile_and_effectful_indices():
    assert variants(SOURCE.replace('char *p;', 'char *p;\n    { int x, table; use(table); }'), 'f') == []
    assert variants(SOURCE.replace('extern char table[];', 'extern volatile char table[];'), 'f') == []
    assert variants(SOURCE.replace('idx * 4', 'idx++ * 4'), 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define table other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []

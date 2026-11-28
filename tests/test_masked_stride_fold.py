from decomprepair.masked_stride_fold import variants

SOURCE = '''
typedef signed int s32;
void f(s32 arg) {
    if (arg) {
        s32 a;
        a = (arg & 0xFFFF) * 2;
        use((((a + (arg & 0xFFFF)) * 8) + (arg & 0xFFFF)) * 4);
    } else {
        s32 b;
    label:
        b = (arg & 0xFFFF) * 2;
        use((((b + (arg & 0xFFFF)) * 8) + (arg & 0xFFFF)) * 4);
    }
}
'''


def test_offers_each_and_both_bounded_strides():
    children = variants(SOURCE, 'f')
    assert len(children) == 3
    assert children[-1][1].count('((arg & 0xFFFF) * 100)') == 2
    assert 's32 a;' not in children[-1][1]


def test_rejects_mutation_escape_extra_uses_and_shadow():
    cases = (
        SOURCE.replace('if (arg) {', 'arg++;\n    if (arg) {'),
        SOURCE.replace('if (arg) {', 'use(&arg);\n    if (arg) {'),
        SOURCE.replace('s32 a;', 's32 a;\n        use(&a);'),
        SOURCE.replace('s32 a;', 's32 a;\n        use(a);'),
        SOURCE.replace('s32 a;', 's32 a;\n        { int x, a; use(a); }'),
        SOURCE.replace('typedef signed int s32;', 'typedef unsigned int s32;'),
    )
    for source in cases:
        # Other independent sites can still be offered.
        assert all('s32 a;' in child for _, child in variants(source, 'f'))


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define arg other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []

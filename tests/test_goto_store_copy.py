from decomprepair.goto_store_copy import variants

SOURCE = '''
typedef signed int s32;
void f(int x) {
    s32 value;
    s32 *ptr;
    if (x) {
        value = *ptr + 1;
        goto store;
    }
    value = 0;
store:
    *ptr = value;
done:
    use();
}
'''


def test_copies_store_into_one_predecessor():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    assert '*ptr = *ptr + 1;\n        goto done;' in children[0][1]
    assert 'store:\n    *ptr = value;' in children[0][1]


def test_rejects_escape_reads_shadow_and_unbraced_control():
    cases = (
        SOURCE.replace('use();', 'use(value);'),
        SOURCE.replace('use();', 'use(&value);'),
        SOURCE.replace('        value = *ptr + 1;', '        if (x)\n        value = *ptr + 1;'),
        SOURCE.replace('    s32 value;', '    s32 value;\n    { int x, value; use(value); }'),
        SOURCE.replace('    s32 *ptr;', '    volatile s32 *ptr;'),
        SOURCE.replace('done:\n', 'done:\n done:\n'),
    )
    for source in cases:
        assert variants(source, 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define ptr other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []

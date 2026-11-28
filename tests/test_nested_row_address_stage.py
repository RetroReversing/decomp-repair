from decomprepair.nested_row_address_stage import variants

SOURCE = '''
typedef unsigned char u8;
typedef signed int s32;
void f(int col) {
    u8 *base;
    s32 offset;
    int result;
    result = outer(col, inner(col + (offset + base)));
}
'''


def test_stages_the_real_row_before_the_nested_call():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert '__repair_row_address = base + offset;' in text
    assert 'inner(col + (__repair_row_address))' in text


def test_rejects_effects_control_and_shadow():
    cases = (
        SOURCE.replace('inner(col +', 'inner(col++ +'),
        SOURCE.replace('inner(col + (offset + base))', 'inner(col + (offset + base), other())'),
        SOURCE.replace('inner(col + (offset + base))', 'inner(col + (offset + base), (*fp)())'),
        SOURCE.replace('inner(col + (offset + base))', 'inner(col + (offset + base), (*(*fp))())'),
        SOURCE.replace('    result = outer', '    if (col)\n    result = outer'),
        SOURCE.replace('    result = outer', 'label:\n    result = outer'),
        SOURCE.replace('    int result;', '    int result;\n    { int offset; use(offset); }'),
        SOURCE.replace('    int result;', '    int result, base;'),
        SOURCE.replace('u8 *base;', 'volatile u8 *base;'),
        SOURCE + '\nint line = __LINE__;\n',
    )
    for source in cases:
        assert variants(source, 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define base other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []

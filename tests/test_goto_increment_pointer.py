from decomprepair.goto_increment_pointer import variants

SOURCE = '''
typedef signed int s32;
extern char table[];
void f(int i) {
    s32 value;
    s32 *ptr;
    if (i) {
        ptr = (i * 4) + table;
        *ptr = *ptr + 1;
        goto done;
    }
    value = 0;
store:
    *ptr = value;
done:
    use();
}
'''


def test_stages_real_pointer_before_shared_store():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert '__repair_increment_ptr = (i * 4) + table;' in text
    assert 'value = *__repair_increment_ptr + 1;' in text
    assert 'ptr = __repair_increment_ptr;' in text
    assert 'goto store;' in text


def test_rejects_later_read_backedge_escape_shadow_and_unbraced_control():
    cases = (
        SOURCE.replace('use();', 'use(value);'),
        SOURCE.replace('use();', 'if (i) goto store;'),
        SOURCE.replace('use();', 'use(&value);'),
        SOURCE.replace('use();', 'use(&ptr);'),
        SOURCE.replace('        ptr =', '        if (i)\n        ptr ='),
        SOURCE.replace('    s32 value;', '    s32 value;\n    { int x, value; use(value); }'),
        SOURCE.replace('extern char table[];', 'extern volatile char table[];'),
        SOURCE + '\nint line = __LINE__;\n',
        SOURCE + '\nclass C {};\n',
    )
    for source in cases:
        assert variants(source, 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define ptr other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []

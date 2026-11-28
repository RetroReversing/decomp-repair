from decomprepair.inline_narrow_param_copy import variants

SOURCE = '''
typedef signed int s32;
typedef unsigned short u16;
void f(s32 arg) {
    u16 value;
    value = arg;
    if (arg) {
        value = arg;
    }
    use(value * 100);
}
'''


def test_keeps_conversion_at_the_read():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert text.count('(void) 0;') == 2
    assert 'use(((u16) arg) * 100);' in text


def test_rejects_mutation_escape_and_shadow():
    cases = (
        SOURCE.replace('use(value * 100);', 'arg++; use(value * 100);'),
        SOURCE.replace('use(value * 100);', 'use(&value);'),
        SOURCE.replace('use(value * 100);', 'value++; use(value * 100);'),
        SOURCE.replace('value = arg;', 'value = arg + 1;'),
        SOURCE.replace('    u16 value;', '    u16 value;\n    { int x, value; use(value); }'),
        SOURCE.replace('u16 value;', 'short value;'),
    )
    for source in cases:
        assert variants(source, 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define value other', '#define arg other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []

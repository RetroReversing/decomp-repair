from decomprepair.masked_comma_copy import variants

SOURCE = '''
typedef signed int s32;
void f(s32 arg) {
    s32 copy;
    int x;
    copy = arg & 0xFFFF;
    if (x) { x = (use(), copy = arg & 0xFFFF, 2); }
    use(copy);
}
'''


def test_inlines_both_statement_and_comma_copies():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert 'copy = arg' not in text
    assert '(use(), (arg & 0xFFFF), 2)' in text
    assert 'use((arg & 0xFFFF))' in text


def test_refuses_mutation_escape_shadow_and_different_masks():
    cases = (
        SOURCE.replace('use(copy);', 'arg++; use(copy);'),
        SOURCE.replace('use(copy);', 'use(&copy);'),
        SOURCE.replace('int x;', 'int x; { int copy; use(copy); }'),
        SOURCE.replace('copy = arg & 0xFFFF,', 'copy = arg & 0xFF,'),
        SOURCE.replace('use(copy);', 'copy += 1; use(copy);'),
        SOURCE.replace('s32 copy;', 'unsigned char copy;'),
    )
    for text in cases:
        assert variants(text, 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define copy other', '#define arg other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []

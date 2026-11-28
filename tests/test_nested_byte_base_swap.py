from decomprepair.nested_byte_base_swap import variants

SOURCE = '''
typedef unsigned char u8;
typedef signed char s8;
extern char table[];
void f(int i) {
    u8 *base;
    int col;
    int row;
    int index;
    base = table;
loop: {
    use(col + (row + table) + *(s8 *)(base + index));
}
    if (i--) goto loop;
}
'''


def test_swaps_the_two_addresses_without_changing_loads():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    assert 'col + (row + base) + *(s8 *)(table + index)' in children[0][1]


def test_rejects_changed_or_escaped_pointer_and_loop_entry():
    cases = (
        SOURCE.replace('    use(', '    base++;\n    use('),
        SOURCE.replace('    use(', '    other(&base);\n    use('),
        SOURCE.replace('    use(', 'inner:\n    use('),
        SOURCE.replace('    if (i--) goto loop;', '    if (i--) goto loop;\n    goto loop;'),
        SOURCE.replace('    int col;', '    int col, table;'),
        SOURCE.replace('extern char table[];', 'extern int table[];'),
        SOURCE.replace('base = table;', 'base = other;'),
    )
    for source in cases:
        assert variants(source, 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define table other', '#define base other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []

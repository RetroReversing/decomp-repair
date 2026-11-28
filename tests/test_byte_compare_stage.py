from decomprepair.byte_compare_stage import variants

SOURCE = '''
typedef unsigned char u8;
extern char table_a[];
extern char table_b[];
void f(int i, int j) {
    if ((u8) *(table_a + i) < (u8) *(table_b + j)) { use(); }
}
'''


def test_stages_only_the_right_byte_read():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert '__repair_compare_byte = (u8) *(table_b + j);' in text
    assert 'if ((u8) *(table_a + i) < __repair_compare_byte)' in text


def test_rejects_side_effects_unbraced_controls_and_volatile():
    cases = (
        SOURCE.replace('table_b + j', 'table_b + j++'),
        SOURCE.replace('table_b + j', 'table_b + get()'),
        SOURCE.replace('    if ((u8)', '    if (i)\n    if ((u8)'),
        SOURCE.replace('    if ((u8)', 'label:\n    if ((u8)'),
        SOURCE.replace('extern char table_a[];', 'extern volatile char table_a[];'),
        SOURCE.replace('use();', 'use(__LINE__);'),
        SOURCE + '\nint line = __LINE__;\n',
    )
    for source in cases:
        assert variants(source, 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define i other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []


def test_rejects_cpp_overload_context():
    assert variants(SOURCE + '\nclass C {};\n', 'f') == []

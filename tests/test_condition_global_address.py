from decomprepair.condition_global_address import variants

SOURCE = '''
typedef unsigned char u8;
extern u8 flag;
void f(int x) {
    if ((flag == 1) || (store(), flag == 1)) { use(); }
}
'''


def test_preserves_both_reads_around_the_call():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert '__repair_byte_address = &flag;' in text
    assert text.count('(*__repair_byte_address)') == 2
    assert 'store()' in text


def test_rejects_unbraced_controls_shadow_address_and_writes():
    cases = (
        SOURCE.replace('    if ((flag', '    if (x)\n    if ((flag'),
        SOURCE.replace('    if ((flag', 'label:\n    if ((flag'),
        SOURCE.replace('int x)', 'int flag)'),
        SOURCE.replace('    if ((flag', '    int y, flag;\n    if ((flag'),
        SOURCE.replace('    if ((flag', '    for (int y, flag; y; y--) { }\n    if ((flag'),
        SOURCE.replace('flag == 1))', '(&flag != 0))'),
        SOURCE.replace('flag == 1))', '(flag = 1)))'),
        SOURCE.replace('extern u8 flag;', 'extern volatile u8 flag;'),
        SOURCE.replace('use();', 'use(__LINE__);'),
    )
    for source in cases:
        assert variants(source, 'f') == []


def test_preprocessor_inputs_are_conservative():
    assert variants(SOURCE + '\nint line = __LINE__;\n', 'f') == []
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define flag other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []


def test_rejects_cpp_overload_context():
    assert variants(SOURCE + '\nclass C {};\n', 'f') == []

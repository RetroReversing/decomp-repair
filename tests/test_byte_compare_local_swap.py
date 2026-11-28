from decomprepair.byte_compare_local_swap import variants

SOURCE = '''
typedef unsigned char u8;
extern char table[];
void f(int i) {
    u8 value;
    if ((u8) *(table + i) < value) { use(); }
}
'''


def test_flips_the_side_and_relation():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    assert 'if (value > (u8) *(table + i))' in children[0][1]
    assert 'if (value <= (u8)' in variants(SOURCE.replace('< value', '>= value'), 'f')[0][1]


def test_rejects_side_effects_volatile_and_nonlocal_values():
    cases = (
        SOURCE.replace('table + i', 'table + i++'),
        SOURCE.replace('table + i', 'table + get()'),
        SOURCE.replace('u8 value;', 'volatile u8 value;'),
        SOURCE.replace('u8 value;', 'int value;'),
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

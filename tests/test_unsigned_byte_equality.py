from decomprepair.unsigned_byte_equality import variants

SOURCE = '''
extern char table[];
void f(int i) {
    if (*(table + 1 + i) == 2) use();
}
'''


def test_casts_only_the_read():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    assert 'if ((unsigned char) *(table + 1 + i) == 2)' in children[0][1]
    assert len(variants(SOURCE.replace('== 2', '!= 0x7f'), 'f')) == 1


def test_rejects_values_or_expressions_where_equality_may_change():
    for expression in ('== 128', '== 0xff', '== 2 + i', '== -1', '< 2'):
        assert variants(SOURCE.replace('== 2', expression), 'f') == []
    assert variants(SOURCE.replace('extern char table[];', 'extern int table[];'), 'f') == []
    assert variants(SOURCE.replace('void f(int i)', 'void f(int table)'), 'f') == []
    assert variants(SOURCE.replace('if (*(table + 1 + i) == 2)', 'MACRO(*(table + 1 + i) == 2)'), 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define table other', '#define i x'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []


def test_rejects_cpp_overload_context():
    assert variants(SOURCE + '\nclass C {};\n', 'f') == []

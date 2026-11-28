from decomprepair.narrow_product_stage import variants

SOURCE = '''
typedef unsigned char u8;
void f(void) {
    u8 n;
    int x;
    int y;
loop: {
    n = data();
    x = n * 4;
    y = x + 1;
    use = call(table + (n * 0x178));
}
    if (x) goto loop;
}
'''


def test_stages_real_product():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert '__repair_product = n * 0x178;' in text
    assert 'call(table + __repair_product)' in text
    assert text.index('__repair_product =') < text.index('x = n * 4')


def test_rejects_mutation_escape_control_or_overflow():
    cases = (
        SOURCE.replace('x = n * 4;', 'x = n++;'),
        SOURCE.replace('y = x + 1;', 'y = call(&n);'),
        SOURCE.replace('    n = data();', '    if (x)\n    n = data();'),
        SOURCE.replace('    x = n * 4;', 'target:\n    x = n * 4;'),
        SOURCE.replace('n * 0x178', 'n * 0x800000'),
        SOURCE.replace('u8 n;', 'int n;'),
        SOURCE.replace('int y;', 'int y;\n    { int n; use = n; }'),
        SOURCE.replace('y = x + 1;', 'y = nested();'),
    )
    for source in cases:
        assert variants(source, 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define n other', '#define __repair_product x'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []

from decomprepair.masked_stride_loop_weight import variants

SOURCE = '''
typedef signed int s32;
extern unsigned char table[];
void f(s32 arg) {
    s32 stride;
    int value;
    stride = (arg & 0xFFFF) * 100;
loop: {
    value = *(table + stride);
    call();
    value = *(table + stride);
}
    if (value) goto loop;
}
'''


def test_offers_staging_and_weighted_real_loads():
    children = variants(SOURCE, 'f')
    assert children
    assert '__repair_stride_mask = arg & 0xFFFF;' in children[0][1]
    assert 'stride = __repair_stride_mask * 100;' in children[0][1]
    assert any('do { do { do { value = *(table + stride);' in child for _, child in children)


def test_rejects_mutation_shadow_and_unbraced_control():
    cases = (
        SOURCE.replace('    stride =', '    arg++;\n    stride ='),
        SOURCE.replace('    stride =', '    use(&arg);\n    stride ='),
        SOURCE.replace('    stride =', '    if (arg)\n    stride ='),
        SOURCE.replace('    s32 stride;', '    s32 stride;\n    { int x, stride; use(stride); }'),
        SOURCE.replace('extern unsigned char table[];', 'extern volatile unsigned char table[];'),
        SOURCE + '\nint line = __LINE__;\n',
        SOURCE + '\nclass C {};\n',
    )
    for source in cases:
        assert variants(source, 'f') == []


def test_preprocessor_inputs_are_conservative():
    for directive in ('#include "x.h"', '#include_next <x.h>', '#import "x.h"', '#define arg other'):
        assert variants(SOURCE, 'f', header=directive) == []
    for flag in ('-DFOO=1', '-include', '-imacros', '-Wp,foo', '-Xpreprocessor', '@flags'):
        assert variants(SOURCE, 'f', flags=[flag]) == []

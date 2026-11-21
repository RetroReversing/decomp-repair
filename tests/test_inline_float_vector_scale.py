from decomprepair.inline_float_vector_scale import FAMILY, variants

SOURCE = '''void f(f32 *vector) {
    f32 x = vector[0] * 0.125f;
    f32 y = vector[1] * 0.125f;
    f32 z = vector[2] * 0.125f;
    output(x, y, z);
}'''
ASM = '''lwc1 $f2, 0($a0)
mul.s $f2, $f2, $f0
lwc1 $f8, 4($a0)
mul.s $f8, $f8, $f0
lwc1 $f4, 8($a0)
mul.s $f4, $f4, $f0
'''


def test_inlines_only_the_three_initial_component_products():
    [(family, child)] = variants(SOURCE, 'f', 'mips', ASM)
    assert family == FAMILY
    assert 'inline static float __repair_float_mul(f32 lhs, f32 rhs)' in child
    for i, var in enumerate('xyz'):
        assert f'f32 {var} = __repair_float_mul(vector[{i}], 0.125f);' in child
    assert 'output(x, y, z);' in child


def test_requires_shared_scale_and_three_read_offsets():
    assert not variants(SOURCE.replace('vector[2] * 0.125f', 'vector[2] * 0.25f'), 'f', 'mips', ASM)
    assert not variants(SOURCE, 'f', 'mips', ASM.replace('8($a0)', '8($a1)'))
    assert not variants(SOURCE, 'f', 'mips', ASM.replace('$f4, $f4, $f0', '$f4, $f4, $f6'))

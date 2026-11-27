from decomprepair.unused_parameter_insert import variants

SOURCE = 'typedef float f32;\ns32 g(u16 *a, u16 *b, f32 x, f32 z)\n{\n    return x <= z;\n}\n'


def test_an_unused_parameter_goes_after_each_parameter_last_first():
    children = [child for _, child in variants(SOURCE, 'g')]
    assert 'f32 z, f32 unused_parameter)' in children[0]
    assert 'f32 x, f32 unused_parameter, f32 z)' in children[2]
    assert 'u16 *a, s32 unused_parameter, u16 *b' in children[-1]
    assert len(children) == 8


def test_no_parameters_or_a_function_pointer_is_left_alone():
    assert variants('void g(void)\n{\n}\n', 'g') == []
    assert variants('void g(void (*f)(int), int a)\n{\n}\n', 'g') == []
    assert variants(variants(SOURCE, 'g')[0][1], 'g') == []

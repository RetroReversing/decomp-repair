from decomprepair import float_cube_square_stage as cube
from decomprepair import float_literal_call_inline as inline


def test_stages_cube_without_changing_multiplication_order():
    source = 'void f(void) {\n    f32 x;\n    f32 y;\n    y = x * x * x;\n}\n'
    out = cube.variants(source, 'f', 'mul.s $f0, $f0, $f0\nmul.s $f2, $f0, $f0')
    assert len(out) == 1
    assert 'repair_float_square = x * x;' in out[0][1]
    assert 'y = repair_float_square * x;' in out[0][1]
    assert not cube.variants(source.replace('f32 x;', 'volatile f32 x;'), 'f', 'mul.s\nmul.s')


def test_inline_only_when_local_is_dead_after_call():
    source = 'void f(void) {\n    f32 x;\n    x = 1.0f;\n    call(x);\n    x = 2.0f;\n    call(x);\n}\n'
    out = inline.variants(source, 'f')
    assert len(out) == 2
    assert 'call(1.0f);' in out[0][1]
    used = 'void f(void) {\n    f32 x;\n    x = 1.0f;\n    call(x);\n    use(x);\n}\n'
    assert not inline.variants(used, 'f')
    assert not inline.variants(source.replace('call(x);', 'call(&x);', 1), 'f')

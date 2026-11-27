"""A constant added before a subtraction, grouped with another operand."""
from decomprepair import registry
from decomprepair.constant_term_regroup import FAMILY, REPAIR, variants

SOURCE = """void f(Obj *o) {
    s16 h;

    h = height(o);
    o->z = (s32) ((h + 0x200) - (random() >> 5));
}
"""


def kids(source=SOURCE):
    return [child for _, child in variants(source, 'f')]


def test_the_constant_moves_to_the_other_operand():
    out = kids()
    assert any('(s32) ((h - ((random() >> 5) - 0x200)));' in child for child in out)
    assert any('(((h - (random() >> 5)) + 0x200))' in child for child in out)


def test_an_unbracketed_sum_that_starts_the_expression():
    out = kids('void f(s32 a, s32 b) {\n    D_x = a + 4 - b;\n}\n')
    assert any('D_x = a - (b - 4);' in child for child in out)


def test_left_alone_when_the_sum_is_not_one_operand_or_a_float():
    assert kids('void f(s32 a, s32 b) {\n    D_x = c * a + 4 - b;\n}\n') == []
    assert kids('void f(s32 a, s32 b) {\n    D_x = a + 4 - b * 2;\n}\n') == []
    assert kids('void f(s32 a, s32 b) {\n    D_x = g(a + 4) - b;\n}\n') == []
    assert kids('void f(f32 a, f32 b) {\n    D_x = 1.5f + 4 - b;\n}\n') == []


def test_declared():
    assert REPAIR['families'] == (FAMILY,)
    assert registry.problems(registry.get('constant_term_regroup')) == []

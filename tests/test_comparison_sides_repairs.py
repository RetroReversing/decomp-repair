"""A comparison of two loads with its sides swapped."""
from decomprepair import comparison_sides_repairs as c


def test_swapped_with_the_operator_flipped():
    source = 'void f(void *a, void *b) {\n    if (M2C_FIELD(a, f32 *, 0x2C) < M2C_FIELD(b, f32 *, 0x2C)) {\n        g();\n    }\n}\n'
    (family, out), = c.variants(source, 'f')
    assert family == 'comparison_sides'
    assert 'if (M2C_FIELD(b, f32 *, 0x2C) > M2C_FIELD(a, f32 *, 0x2C))' in out


def test_left_alone_for_arithmetic_operands():
    assert c.variants('void f(s32 a, s32 *p) {\n    if (a + 1 < p[0] - 2) {\n        g();\n    }\n}\n', 'f') == []

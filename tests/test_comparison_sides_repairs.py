"""A comparison of two loads with its sides swapped."""
from decomprepair import comparison_sides_repairs as c


def test_swapped_with_the_operator_flipped():
    source = 'void f(void *a, void *b) {\n    if (M2C_FIELD(a, f32 *, 0x2C) < M2C_FIELD(b, f32 *, 0x2C)) {\n        g();\n    }\n}\n'
    (family, out), = c.variants(source, 'f')
    assert family == 'comparison_sides'
    assert 'if (M2C_FIELD(b, f32 *, 0x2C) > M2C_FIELD(a, f32 *, 0x2C))' in out


def test_left_alone_for_arithmetic_operands():
    assert c.variants('void f(s32 a, s32 *p) {\n    if (a + 1 < p[0] - 2) {\n        g();\n    }\n}\n', 'f') == []


def test_the_projects_field_cells_are_operands():
    code = """void run(Obj *o)
{
    f32 v[3];
    if ((!(((Field_f32 *) (((char *) o) + 0x14))->v < v[1])) && (!(v[1] < ((Field_f32 *) (((char *) o) + 0x18))->v)))
    {
        go(o);
    }
}
"""
    found = [text for _, text in c.variants(code, "run")]
    assert any('!(v[1] > ((Field_f32 *) (((char *) o) + 0x14))->v)' in t for t in found)

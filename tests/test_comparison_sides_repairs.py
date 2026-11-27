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


def test_every_comparison_is_offered():
    source = 'void f(s32 *a, s32 *b) {\n' + ''.join(f'    if (a[{i}] < b[{i * 7 + 1}]) g{i}();\n' for i in range(6)) + '}\n'
    found = [text for _, text in c.variants(source, 'f')]
    assert any('b[36] > a[5]' in text and 'a[0] < b[1]' in text for text in found)


def test_repeated_comparisons_swap_together():
    source = ('void f(f32 *a, f32 *b, f32 *c) {\n'
              + ''.join(f'    if (a[{i}] < b[{i}]) {{ c[{i}] = a[{i}]; }}\n    if (c[{i}] < b[{i}]) {{ g(); }}\n'
                        for i in range(3))
              + '}\n')
    family, first = c.variants(source, 'f')[0]
    assert family == 'comparison_sides'
    assert all(f'if (b[{i}] > a[{i}])' in first and f'if (c[{i}] < b[{i}])' in first for i in range(3))


def test_casts_move_with_their_operands_and_every_comparison_swaps_at_once():
    source = '''void f(void *a) {
    if (((u8) M2C_FIELD(a, u8 *, 0x7C) >= (u8) M2C_FIELD(&limits, u8 *, 0)) && ((u8) M2C_FIELD(a, u8 *, 0x7D) >= (u8) M2C_FIELD(&limits, u8 *, 1)) && ((u8) M2C_FIELD(a, u8 *, 0x7D) >= (u32) D_80000000)) {
        g();
    }
}
'''
    every = ('if (((u8) M2C_FIELD(&limits, u8 *, 0) <= (u8) M2C_FIELD(a, u8 *, 0x7C)) && '
             '((u8) M2C_FIELD(&limits, u8 *, 1) <= (u8) M2C_FIELD(a, u8 *, 0x7D)) && '
             '((u32) D_80000000 <= (u8) M2C_FIELD(a, u8 *, 0x7D))) {')
    assert any(every in text for _, text in c.variants(source, 'f'))


def test_a_typed_dereference_is_one_operand():
    source = ('void f(void *a) {\n    if (*(s32 *)((kind * 4) + D_80010000) < M2C_FIELD(a, s32 *, 0x38)) {\n'
              '        g();\n    }\n}\n')
    found = [text for _, text in c.variants(source, 'f')]
    assert any('if (M2C_FIELD(a, s32 *, 0x38) > *(s32 *)((kind * 4) + D_80010000))' in t for t in found)


def test_a_typed_dereference_of_a_cast_sum_or_a_name():
    source = 'void f(char *p) {\n    if ((x->a < *(u16 *)(s8 *)(p + 2)) && (*(s32 *)&D_80010000 > x->b)) {\n        g();\n    }\n}\n'
    found = [text for _, text in c.variants(source, 'f')]
    assert any('*(u16 *)(s8 *)(p + 2) > x->a' in t for t in found)
    assert any('x->b < *(s32 *)&D_80010000' in t for t in found)

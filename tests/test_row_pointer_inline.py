"""A row pointer local `p = TABLE[i];` read as `p[k]`, written as `TABLE[i][k]` (an N64 colour interpolator)."""
from decomprepair import row_pointer_inline as r

TINT = '''void shade(void) {
    f32 c0[3];
    f32 r;
    f32 g;
    u8 *tint;
    u32 col;

    c0[0] = V[0].cn[0];
    c0[1] = V[0].cn[1];
    tint = TABLE[gIndex];
    r = c0[0] * tint[0];
    r /= 255.0;
    g = c0[1];
    g *= tint[1];
    col = (u32) r | tint[2];
    gOut = col + g;
}
'''
INLINED = '''void shade(void) {
    f32 c0[3];
    f32 r;
    f32 g;
    u32 col;

    c0[0] = V[0].cn[0];
    c0[1] = V[0].cn[1];
    r = c0[0] * TABLE[gIndex][0];
    r /= 255.0;
    g = c0[1];
    g *= TABLE[gIndex][1];
    col = (u32) r | TABLE[gIndex][2];
    gOut = col + g;
}
'''


def test_the_row_reads_are_written_through_the_table_and_the_local_goes():
    assert r.variants(TINT, 'shade') == [(r.FAMILY, INLINED)]


def test_a_declaration_with_the_assignment_is_dropped_with_it():
    src = 'u8 f(s32 i) {\n    u8 *p = T[i + 1];\n    return p[0] + p[2];\n}\n'
    assert r.variants(src, 'f') == [(r.FAMILY, 'u8 f(s32 i) {\n    return T[i + 1][0] + T[i + 1][2];\n}\n')]


def test_not_when_the_row_could_change_before_a_read():
    called = 'void f(void) {\n    u8 *p;\n    p = T[gIndex];\n    g(p[0]);\n    h = p[1];\n}\n'
    assert r.variants(called, 'f') == []
    written = 'void f(void) {\n    u8 *p;\n    p = T[gIndex];\n    a = p[0];\n    gIndex = 2;\n    b = p[1];\n}\n'
    assert r.variants(written, 'f') == []


def test_not_when_the_local_is_used_other_than_by_index_or_written_again():
    deref = 'void f(void) {\n    u8 *p;\n    p = T[gIndex];\n    a = *p;\n}\n'
    assert r.variants(deref, 'f') == []
    stepped = 'void f(void) {\n    u8 *p;\n    p = T[gIndex];\n    a = p[0];\n    p++;\n    b = p[0];\n}\n'
    assert r.variants(stepped, 'f') == []

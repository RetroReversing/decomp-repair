"""A float parameter in the prototype of a callee m2c declared without parameters."""
from decomprepair import float_prototype_repairs as f

SOURCE = '''f32 g();
s32 h();

f32 k(s32 arg0, f32 arg1, f32 arg2) {
    f32 a;
    f32 b;

    a = g(arg0);
    b = g(arg1);
    h(arg2 > 0.0f);
    return a + b + g(arg2);
}
'''


def test_the_prototype_and_the_callers_own_parameter():
    # An N64 function at 88%: exact with `f32 g(f32);` and its arg0, passed only to g, an f32.
    (family, proto), (_, floated) = f.variants(SOURCE, 'k')
    assert family == 'float_prototype'
    assert 'f32 g(f32);' in proto and 'f32 k(s32 arg0,' in proto and 's32 h();' in proto
    assert 'f32 g(f32);' in floated and 'f32 k(f32 arg0,' in floated


def test_left_alone_without_a_float_argument_or_with_differing_calls():
    assert f.variants(SOURCE.replace('b = g(arg1);', 'b = g(arg0);').replace('g(arg2)', 'g(arg0)'), 'k') == []
    assert f.variants(SOURCE.replace('b = g(arg1);', 'b = g(arg1, 2);'), 'k') == []
    assert f.variants(SOURCE.replace('f32 g();', 'f32 g(f32);'), 'k') == []


def test_a_load_through_a_float_pointer_is_a_float_argument():
    # An N64 table update: the callee only ever gets table fields, so no named f32 shows its type.
    source = '''f32 g();

f32 k(s32 i) {
    return g(*((f32 *)((s8 *)&D_80000000 + i))) + g(*(f32 *)(D_80000004 + i)) + g(M2C_FIELD(D_80000008, f32 *, 4));
}
'''
    (family, proto), = f.variants(source, 'k')
    assert 'f32 g(f32);' in proto


def test_an_integer_load_or_a_comparison_of_a_float_load_is_not():
    source = '''f32 g();

f32 k(s32 i) {
    return g(*(s32 *)i) + g(*(f32 *)i > 0.0f);
}
'''
    assert f.variants(source, 'k') == []

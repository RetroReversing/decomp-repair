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

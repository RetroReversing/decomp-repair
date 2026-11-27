from decomprepair import sink_float_constant_past_call as repair

SOURCE = '''void f(void) {
    f32 x;
    f32 y;
    x = -0.05f;
    y = compute(2) * 3.0f;
    consume(x, y);
}
'''


def test_moves_an_unescaped_local_initialization_after_call():
    out = repair.variants(SOURCE, 'f')
    assert len(out) == 1
    assert out[0][1].index('y = compute') < out[0][1].index('x = -0.05f')


def test_rejects_escaped_or_call_used_local():
    assert not repair.variants(SOURCE.replace('consume(x, y);', 'consume(&x, y);'), 'f')
    assert not repair.variants(SOURCE.replace('compute(2)', 'compute(x)'), 'f')
    assert not repair.variants(SOURCE, 'f', 'typedef volatile float f32;')

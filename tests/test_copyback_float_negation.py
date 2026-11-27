from decomprepair import copyback_float_negation as repair

ASM = 'c.lt.s $f0, $f4\nbc1t .L1\nmov.s $f6, $f4\nneg.s $f6, $f4\n'
SOURCE = '''void f(void) {
    f32 x;
    f32 y;
    if (x > 0.0f) {
        y = x;
    } else {
        y = -x;
    }
    x = y;
    consume(x);
}
'''


def test_select_then_copy_back():
    out = repair.variants(SOURCE, 'f', ASM)
    assert len(out) == 1
    assert 'y = x;' in out[0][1]
    assert 'if (!(x > 0.0f)) { y = -y; }' in out[0][1]
    assert 'x = y;' in out[0][1]


def test_rejects_volatile_or_wrong_target():
    assert not repair.variants(SOURCE, 'f', ASM.replace('bc1t', 'bc1f'))
    assert not repair.variants(SOURCE.replace('f32 x;', 'volatile f32 x;'), 'f', ASM)
    assert not repair.variants(SOURCE, 'f', ASM, 'typedef volatile float f32;')

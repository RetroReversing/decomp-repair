from decomprepair import staged_float_negation as repair

ASM = 'c.lt.s $f0, $f2\nbc1t .L1\nmov.s $f4, $f2\nneg.s $f4, $f2\n'
SOURCE = '''void f(void) {
    f32 x;
    f32 y;
    y = -x;
    if (x > 0.0f) {
        y = x;
    }
    consume(y);
}
'''


def test_stage_result_before_consumer():
    out = repair.variants(SOURCE, 'f', ASM)
    assert len(out) == 1
    assert 'f32 repair_float_select;' in out[0][1]
    assert 'y = repair_float_select;' in out[0][1]


def test_requires_plain_float_locals_and_target_evidence():
    assert not repair.variants(SOURCE, 'f', ASM.replace('bc1t', 'bc1f'))
    assert not repair.variants(SOURCE.replace('f32 x;', 'volatile f32 x;'), 'f', ASM)
    assert not repair.variants(SOURCE, 'f', ASM, 'typedef volatile float f32;')

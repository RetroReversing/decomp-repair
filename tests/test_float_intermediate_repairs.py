from decomprepair.float_intermediate_repairs import repeated_products


def test_stage_repeated_float_products_and_the_final_conversion():
    source = '''extern f32 samples[], lefts[], rights[];
void f(s16 *a, s16 *b, s16 *c) {
    f32 q, r, t, v, w;
    *a = (s32)(q*((1.0f-w)*samples[i]+w*samples[i+1])*15.0f);
    r = q*((1.0f-w)*samples[i]+w*samples[i+1]);
    if (flag) {
        *b = (s32)(r*((1.0f-w)*samples[i]+w*samples[i+1])*25.0f);
        v = r*((1.0f-w)*samples[i]+w*samples[i+1])*25.0f;
    }
    *c = (s32)(((1.0f-w)*lefts[i]+w*rights[i])*15.0f);
}
'''
    rows = [
        ('r', 'mul.s $f0, $f6, $f2', 'mul.s $f2, $f6, $f2'),
        ('r', 'trunc.w.s $f2, $f0', 'trunc.w.s $f0, $f2'),
        ('r', 'mfc1 $v0, $f2', 'mfc1 $v0, $f0'),
    ]
    [(family, complete), (_, partial)] = repeated_products(source, 'f', rows * 2)
    assert family == 'repeated_float_product_staging'
    assert 't = q*((1.0f-w)*samples[i]+w*samples[i+1]);\n    *a = (s32)(t * 15.0f);' in complete
    assert 'r = q * t;' in complete
    assert 'r = (1.0f-w)*lefts[i]+w*rights[i]; *c = (s32)(r * 15.0f);' in complete
    assert '*c = (s32)(((1.0f-w)*lefts' in partial
    assert not repeated_products(source, 'f', rows)
    assert not repeated_products(source.replace('    *a =', '    if (flag)\n        *a ='), 'f', rows * 2)
    assert not repeated_products(source.replace('t, v', 'v'), 'f', rows * 2)

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


def test_stage_subtracted_product_when_two_matched_load_product_pairs_are_swapped():
    from decomprepair.float_intermediate_repairs import repeated_products

    source = '''f32 f(void *in) {
    f32 first;
    f32 second;
    f32 gain;
    f32 value;
    first = M2C_FIELD(in, f32 *, 24);
    second = M2C_FIELD(in, f32 *, 12);
    gain = M2C_FIELD(in, f32 *, 16);
    value = (first * gain) - (second * gain);
    return value;
}
'''
    target = ['lwc1 $f6, 0xc($a0)', 'mul.s $f4, $f6, $f4',
              'lwc1 $f0, 0x18($a0)', 'mul.s $f8, $f0, $f8']
    rows = list(zip(('i', 'r', 'i', 'r'), target, target[2:] + target[:2]))
    family, fixed = repeated_products(source, 'f', rows)[0]
    assert family == 'staged_subtracted_float_product'
    assert 'f32 repair_subtracted_product;' in fixed
    assert 'repair_subtracted_product = (second * gain);' in fixed
    assert 'value = (first * gain) - repair_subtracted_product;' in fixed
    assert not repeated_products(source.replace('in, f32 *, 12', 'in, f32 *, 28'), 'f', rows)
    assert not repeated_products(source.replace('second =', 'second = gain; second ='), 'f', rows)
    assert not repeated_products(source, 'f', rows[:-1])


def test_stage_left_field_for_two_swapped_comparison_loads():
    from decomprepair.float_intermediate_repairs import repeated_products

    source = '''s32 f(void *a, void *b) {
    f32 limit;
    limit = M2C_FIELD(b, f32 *, 0);
    if (M2C_FIELD(a, f32 *, 40) < limit) { return 1; }
    return 0;
}'''
    first, second = 'lwc1 $f0, 0x28($s0)', 'lwc1 $f2, ($s1)'
    compare = 'c.lt.s $f0, $f2'
    rows = [('i', first, second), ('i', second, first), (' ', compare, compare)]
    fixed = dict(repeated_products(source, 'f', rows))['staged_float_comparison_load']
    assert 'repair_compare_left = M2C_FIELD(a, f32 *, 40);' in fixed
    assert 'if (repair_compare_left < limit)' in fixed
    assert not repeated_products(source, 'f', rows[:-1])
    assert not repeated_products(source.replace('40', '44'), 'f', rows)


def test_measured_exchange_swaps_only_the_two_plain_float_declarations():
    from decomprepair.float_intermediate_repairs import repeated_products

    source = '''void f(void *p) {
    f32 value;
    f32 other;
    f32 total;
    total = a + b;
    status = 0;
    if (total != 0.0f) {
        value = M2C_FIELD(p, f32 *, 0);
        use(value / total);
    }
}'''
    rows = [('r', 'add.s $f10, $f4, $f0', 'add.s $f14, $f4, $f0'),
            ('r', 'c.eq.s $f10, $f18', 'c.eq.s $f14, $f18'),
            ('r', 'lwc1 $f14, ($a1)', 'lwc1 $f10, ($a1)'),
            ('r', 'div.s $f4, $f0, $f10', 'div.s $f4, $f0, $f14')]
    fixed = dict(repeated_products(source, 'f', rows))['measured_float_declaration_swap']
    assert 'f32 total;\n    f32 other;\n    f32 value;' in fixed
    assert fixed.split('total =', 1)[1] == source.split('total =', 1)[1]
    assert not repeated_products(source.replace('*, 0', '*, 4'), 'f', rows)
    assert not repeated_products(source, 'f', rows[:-1] + [('r', rows[-1][1], 'div.s $f4, $f0, $f2')])

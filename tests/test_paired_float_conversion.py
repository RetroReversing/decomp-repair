from decomprepair.float_intermediate_repairs import repeated_products

SOURCE = """void f(void) {
    f32 saved;
    f32 value;
    f32 bound;
    saved = value;
    if ((value >= 0.0f) && (((s32) value) < bound)) {
        x = a - (value * ax);
        y = b - (value * ay);
        z = c - (((int) value) * az);
    }
}"""
ROWS = [
    ('i', 'swc1 $f0, 0x10($sp)', 'swc1 $f4, 0x20($sp)'),
    ('>', '', 'trunc.w.s $f0, $f4'),
    ('>', '', 'mfc1 $v0, $f0'),
    ('>', '', 'mtc1 $v0, $f0'),
    ('>', '', 'cvt.s.w $f0, $f0'),
    (' ', 'c.lt.s $f0, $f24', 'c.lt.s $f0, $f24'),
    ('r', 'mul.s $f2, $f0, $f12', 'mul.s $f2, $f4, $f12'),
    ('r', 'mul.s $f4, $f0, $f6', 'mul.s $f4, $f4, $f6'),
    (' ', 'mul.s $f0, $f0, $f8', 'mul.s $f0, $f0, $f8'),
]


def test_removes_both_truncations_in_one_candidate():
    (family, text), = repeated_products(SOURCE, 'f', ROWS)
    assert family == 'untruncated_float_compare_and_product'
    assert '(saved < bound)' in text
    assert 'z = c - (saved * az);' in text
    assert 'x = a - (value * ax);' in text


def test_keeps_casts_if_target_also_truncates():
    rows = ROWS[:]
    rows[1] = ('r', 'trunc.w.s $f2, $f0', rows[1][2])
    assert repeated_products(SOURCE, 'f', rows) == []


def test_rejects_intervening_write_to_saved_float():
    source = SOURCE.replace('        x =', '        saved = bound;\n        x =')
    assert repeated_products(source, 'f', ROWS) == []

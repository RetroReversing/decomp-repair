from decomprepair import byte_sign_test as m

SOURCE = '''void f(u16 *p) {
    u16 t;

    t = p[0] - 1;
    p[0] = t;
    if (t & 0x8000) {
        g();
    }
    if (!(t & 0x8000)) {
        h();
    }
}
'''


def test_a_halfword_sign_bit_mask_is_a_signed_compare():
    [(family, out)] = m.variants(SOURCE, 'f')
    assert family == 'halfword_sign_test'
    assert 'if ((s16) t < 0) {' in out and 'if ((s16) t >= 0) {' in out and '0x8000' not in out


def test_other_widths_stay():
    assert m.variants(SOURCE.replace('u16 t;', 's32 t;'), 'f') == []

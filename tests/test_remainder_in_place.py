from decomprepair.remainder_in_place import FAMILY, variants

SOURCE = '''extern char D_80125FA0[];

s32 f(s32 arg0) {
    s32 var_a0;
    s32 var_v0;
    s32 var_v1;

    var_a0 = arg0;
    var_v1 = var_a0 + 1;
    if (D_80125FA0[var_a0] == 0) {
        do {
            var_v0 = var_v1;
            if (var_v1 < 0) {
                var_v0 = var_a0 + 8;
            }
            var_a0 = var_v1 - ((var_v0 >> 3) * 8);
            var_v1 = var_a0 + 1;
        } while (D_80125FA0[var_a0] == 0);
    }
    return var_a0;
}
'''


def children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_remainder_goes_in_place_and_the_carrier_goes():
    """The exact child on an N64 function (SN GCC 2.7.2 -O1): 710 -> 0."""
    texts = children()
    assert len(texts) == 2
    in_place = texts[1]
    assert 'var_a0 = (var_a0 + 1) % 8;' in in_place
    assert 'var_v1' not in in_place
    assert 'var_v0' not in in_place
    assert '>> 3' not in in_place
    assert 'var_a0 = arg0;' in in_place


def test_the_carrier_kept_is_the_first_child():
    plain = children()[0]
    assert 'var_a0 = var_v1 % 8;' in plain
    assert 'var_v1 = var_a0 + 1;' in plain
    assert 'var_v0' not in plain


def test_a_bias_against_the_dividend_itself():
    source = '''s32 f(s32 a) {
    s32 b;
    s32 r;
    s32 t;
    t = a * 3;
    b = t;
    if (t < 0) b = t + 0xF;
    r = t - ((b >> 4) << 4);
    return r;
}
'''
    texts = children(source)
    assert len(texts) == 1
    assert 'r = t % 16;' in texts[0]
    assert 'b = t' not in texts[0]
    assert 's32 b;' not in texts[0]


def test_nothing_when_the_bias_does_not_fit_the_shift():
    assert children(SOURCE.replace('var_a0 + 8;', 'var_a0 + 9;')) == []


def test_nothing_when_the_carrier_is_not_always_the_sum():
    source = SOURCE.replace('    var_v1 = var_a0 + 1;\n    if', '    var_v1 = var_a0 + 2;\n    if')
    assert children(source) == []


def test_nothing_when_the_index_changes_without_the_carrier():
    source = SOURCE.replace('    var_a0 = arg0;\n', '    var_a0 = arg0;\n    var_a0 = var_a0 * 2;\n')
    assert children(source) == []

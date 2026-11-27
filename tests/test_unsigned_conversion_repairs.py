"""m2c's expansion of a float converted to an unsigned integer, as the conversion."""
from decomprepair import unsigned_conversion_repairs as u

SOURCE = '''s32 f(void *arg0) {
    s32 ret;
    f32 temp_fv1;

    temp_fv1 = (f32) (M2C_FIELD(arg0, u8 *, 4) * 0xA);
    if (temp_fv1 >= 2.1474836e9f) {
        ret = ((s32) (temp_fv1 - 2.1474836e9f) | 0x80000000) & 0xFF;
    } else {
        ret = (s32) temp_fv1 & 0xFF;
    }
    return ret;
}
'''


def test_the_conversion_with_its_mask_and_as_a_narrow_cast():
    # An N64 function at 84.1%: exact as `(u8) (u32) temp_fv1`.
    (family, masked), (_, narrow) = u.variants(SOURCE, 'f')
    assert family == 'float_unsigned_conversion'
    assert '    ret = (u32) temp_fv1 & 0xFF;\n    return ret;' in masked
    assert '    ret = (u8) (u32) temp_fv1;\n    return ret;' in narrow
    assert '2.1474836e9f' not in narrow


def test_other_spellings_of_the_test():
    flipped = SOURCE.replace('if (temp_fv1 >= 2.1474836e9f) {', 'if (!(temp_fv1 >= 2.1474836e9f)) {')
    assert u.variants(flipped, 'f')
    stray = SOURCE.replace('        ret = ((s32)', '        register ret = ((s32)')
    assert any('ret = (u32) temp_fv1 & 0xFF;' in t for _, t in u.variants(stray, 'f'))


def test_left_alone_otherwise():
    assert u.variants(SOURCE.replace(' | 0x80000000', ''), 'f') == []
    assert u.variants(SOURCE.replace('ret = (s32) temp_fv1', 'other = (s32) temp_fv1'), 'f') == []


JOINED = '''void f(s32 x)
{
    f32 v;
    f32 t;
    s32 r;
    v = (f32) x;
    if (v > 0.0f) {
        if (v >= 2.1474836e9f) {
            t = v - 2.1474836e9f;
            goto block_7;
        }
        goto block_6;
    }
    v = -(f32) x;
    if (v >= 2.1474836e9f) {
        t = v - 2.1474836e9f;
block_7:
        r = (s32) t | 0x80000000;
    } else {
block_6:
        r = (s32) v;
    }
    g(r);
}
'''


def test_cross_jumped_conversions_of_two_arms_are_written_as_two_conversions():
    found = [text for _, text in u.variants(JOINED, 'f')]
    assert 'if (v > 0.0f) { r = (u32) v; } else { v = -(f32) x; r = (u32) v; }\n    g(r);' in found[0]
    assert 'goto' not in found[0] and '2.1474836e9f' not in found[0]


def test_a_label_another_goto_reaches_keeps_the_arms_as_they_are():
    source = JOINED.replace('    g(r);\n', '    goto block_6;\n')
    assert all('2.1474836e9f' in text for _, text in u.variants(source, 'f'))

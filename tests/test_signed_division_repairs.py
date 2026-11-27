"""m2c's signed power-of-two division expansion, as `/` and `%`."""
from decomprepair import signed_division_repairs as d

SOURCE = '''f32 f(f32 arg0) {
    s32 temp_v0;
    s32 var_v0;

    temp_v0 = g();
    var_v0 = temp_v0 >> 0x10;
    if (temp_v0 < 0) {
        var_v0 = (s32) (temp_v0 + 0xFFFF) >> 0x10;
    }
    return (f32) (temp_v0 - (var_v0 << 0x10)) * 0.000015258789f * arg0;
}
'''


def test_the_remainder():
    (family, out), = d.variants(SOURCE, 'f')
    assert family == 'signed_division'
    assert 'return (f32) (temp_v0 % 0x10000) * 0.000015258789f * arg0;' in out
    assert 'var_v0' not in out


def test_left_alone_for_another_correction():
    assert d.variants(SOURCE.replace('0xFFFF)', '0xFFFE)'), 'f') == []


SHARED = '''void f(void) {
    s32 temp_lo;
    s32 temp_v0;
    temp_lo = D_1 * D_2;
    temp_v0 = temp_lo >> 0x14;
    if (temp_lo < 0) {
        temp_v0 = (s32) (temp_lo + 0xFFFFF) >> 0x14;
    }
    D_3 = (s16) temp_v0;
    temp_v0 = D_1 * D_4;
    D_5 = (s16) temp_v0;
}
'''


def test_a_quotient_temporary_reused_for_the_next_value_is_divided_only_up_to_its_next_assignment():
    (family, out), = d.variants(SHARED, 'f')
    assert 'D_3 = (s16) (temp_lo / 0x100000);' in out
    assert 'temp_v0 = D_1 * D_4;\n    D_5 = (s16) temp_v0;' in out


def test_the_right_side_of_the_reassignment_still_reads_the_quotient():
    (family, out), = d.variants(SHARED.replace('D_1 * D_4', 'temp_v0 + 1'), 'f')
    assert 'temp_v0 = (temp_lo / 0x100000) + 1;' in out

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

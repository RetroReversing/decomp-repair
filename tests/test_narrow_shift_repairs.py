"""m2c's shift pair for a narrow variable, as the s16 variable it was."""
from decomprepair import narrow_shift_repairs as n

SOURCE = '''u16 f(s16 arg0, s32 arg1) {
    s32 temp_v0;
    s32 var_v0;

    if ((arg1 & 0xFFFF) == 1) {
        var_v0 = g(arg0) << 0x10;
    } else {
        var_v0 = (arg0 - 1) << 0x10;
    }
    temp_v0 = var_v0 >> 0x10;
    return temp_v0;
}
'''


def test_written_as_s16():
    # An N64 function and its twin: 335 each, exact this way.
    (family, out), = n.variants(SOURCE, 'f')
    assert family == 'narrow_shift_pair'
    assert '    s16 var_v0;\n' in out and 'var_v0 = g(arg0);' in out and 'var_v0 = (arg0 - 1);' in out
    assert 'temp_v0 = var_v0;' in out and '<<' not in out and '>>' not in out


def test_left_alone_otherwise():
    assert n.variants(SOURCE.replace('    return temp_v0;', '    return var_v0;'), 'f') == []  # read unshifted
    assert n.variants(SOURCE.replace('var_v0 >> 0x10', 'var_v0 >> 0x18'), 'f') == []  # amounts differ

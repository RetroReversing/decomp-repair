"""m2c's polling loop with the next counter in its body, and its double-to-unsigned expansion, written back."""
from decomprepair import loop_shape_repairs as m

POLL = '''void f(s32 arg0) {
    s32 var_s0;

    g(arg0 & 0xFF);
    do {
        var_s0 = 0;
    } while (h(&D, 0, 0) == 0);
    do {
        h(&D, 0, 1);
        var_s0 += 1;
    } while (var_s0 < 4);
}
'''

CONVERSION = '''f64 f(f64 arg0) {
    f64 var_fv1;
    s32 var_v1;

    if (D_800D6800 <= arg0) {
        var_v1 = (s32) (arg0 - D_800D6800) | 0x80000000;
    } else {
        var_v1 = (s32) arg0;
    }
    var_fv1 = (f64) var_v1;
    if (var_v1 < 0) {
        var_fv1 += D_800D6808;
    }
    return var_fv1;
}
'''


def test_the_empty_polling_loop():
    # An N64 function (11 instructions) at 86%: exact this way.
    (family, out), = m.variants(POLL, 'f')
    assert family == 'do_constant_body'
    assert '    while (h(&D, 0, 0) == 0) {\n    }\n    var_s0 = 0;\n    do {' in out


def test_the_round_trip_conversion():
    # An N64 function: exact as the casts.
    (family, both), (_, one) = m.variants(CONVERSION, 'f')
    assert family == 'double_unsigned_conversion'
    assert 'return (f64) (u32) arg0;\n}' in both and 'if' not in both[both.index('{'):]
    assert '    var_v1 = (u32) arg0;\n    var_fv1 = (f64) var_v1;' in one


def test_left_alone_otherwise():
    assert m.variants(POLL.replace('var_s0 = 0;\n    } while (h', 'var_s0 = k();\n    } while (h'), 'f') == []
    assert m.variants(CONVERSION.replace('| 0x80000000', '| 0x40000000'), 'f') == []

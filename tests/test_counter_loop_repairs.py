"""m2c's masked counter loop as a u16 for loop, and an argument it left unset dropped."""
from decomprepair import counter_loop_repairs as c

SOURCE = '''s32 g(s32, s32);
s32 h(s32);

void f(void) {
    s32 var_a0;
    s32 var_s0;

    var_s0 = 0;
    var_a0 = 0 & 0xFFFF;
    do {
        g(var_a0, 0);
        var_a0 = var_s0 & 0xFFFF;
        ++var_s0;
    } while ((u32) (var_s0 & 0xFFFF) < 4U);
    h(var_a0);
}
'''


def test_the_loop_and_then_the_unset_argument():
    # An N64 function: 92% as m2c wrote it, 90% with the loop alone, exact with both.
    (family, loop), (_, both) = c.variants(SOURCE, 'f')
    assert family == 'u16_counter_loop'
    assert '''    {
        u16 __repair_i;
        for (__repair_i = 0; __repair_i < 4; __repair_i++) {
            g(__repair_i, 0);
        }
    }
''' in loop
    assert '    h(var_a0);' in loop
    assert '    h();' in both and 's32 h();' in both and 'var_a0' not in both and 'var_s0' not in both


def test_a_counter_zeroed_earlier_and_left_alone_otherwise():
    earlier = SOURCE.replace('    var_s0 = 0;\n    var_a0', '    var_s0 = 0;\n    k();\n    var_a0')
    assert c.variants(earlier, 'f')
    assert c.variants(SOURCE.replace('    var_s0 = 0;\n', '    var_s0 = 1;\n'), 'f') == []



SINGLE = '''void f(void) {
    s32 temp_v1;
    s32 var_a0;

    var_a0 = 0;
    do {
        temp_v1 = (var_a0 & 0xFFFF) * 2;
        *(temp_v1 + &D_800E097E) = 0;
        var_a0 += 1;
    } while ((u32) (var_a0 & 0xFFFF) < 4U);
}
'''


def test_a_single_masked_counter():
    (_, out), = c.variants(SINGLE, 'f')
    assert 'temp_v1 = __repair_i * 2;' in out and 'for (__repair_i = 0; __repair_i < 4; __repair_i++) {' in out
    assert 'var_a0' not in out
    assert c.variants(SINGLE.replace('*(temp_v1 + &D_800E097E) = 0;', 'g(var_a0);'), 'f') == []  # used unmasked

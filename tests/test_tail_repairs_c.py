"""Round-six repairs: a value kept in the variable it came from, and argument registers that are only temporaries."""
from decomprepair import source_variable_reuse_repairs as reuse
from decomprepair import target_call_arity_repairs as arity

CRC = '''s32 f(u8 *arg0, s32 arg1) {
    s32 ret;
    u32 temp_a2;
    u32 var_a2;

    var_a2 = g(arg0, arg1);
    temp_a2 = ~var_a2;
    ret = ((temp_a2 << 8) | ((temp_a2 >> 8) & 0xFF)) & 0xFFFF;
    return ret;
}
'''


def test_the_value_stays_in_its_variable_and_the_mask_is_its_own_step():
    # An N64 CRC routine's tail: 99.1%; the reuse alone 99.7%; with the masked step split off, exact.
    (family, kept), (_, split) = reuse.variants(CRC, 'f')
    assert family == 'source_variable_reuse'
    assert '    var_a2 = ~var_a2;\n    ret = ((var_a2 << 8) | ((var_a2 >> 8) & 0xFF)) & 0xFFFF;' in kept
    assert ('    var_a2 = ~var_a2;\n    var_a2 = (var_a2 << 8) | ((var_a2 >> 8) & 0xFF);\n    ret = var_a2 & 0xFFFF;'
            in split)
    assert 'temp_a2 =' not in split


def test_left_alone_when_the_source_is_read_again_or_types_differ():
    assert reuse.variants(CRC.replace('    return ret;', '    return ret + var_a2;'), 'f') == []
    assert reuse.variants(CRC.replace('    u32 temp_a2;', '    s32 temp_a2;'), 'f') == []


DIVIDE = '''void f(void *arg0) {
    s32 q;
    u8 r;

    q = (M2C_FIELD(arg0, u8 *, 0x185) + 1) / 3;
    r = (M2C_FIELD(arg0, u8 *, 0x185) + 1) % 3;
    M2C_FIELD(arg0, u8 *, 0x185) = r;
    g(0, q);
}
'''
DIVIDE_ASM = '''lbu        $a0, 0x185($s0)
addiu      $a0, $a0, 0x1
mult       $a0, $v0
sra        $v1, $a0, 31
mfhi       $a2
subu       $v1, $a2, $v1
sll        $v0, $v1, 1
addu       $v0, $v0, $v1
subu       $a0, $a0, $v0
sb         $a0, 0x185($s0)
jal        g
addu       $a0, $zero, $zero
'''


def test_a_divisions_scratch_register_is_not_an_argument():
    # `mfhi $a2` then `subu $v1, $a2, $v1` computed a remainder: the call took one argument, not three (exact so).
    assert arity.calls(DIVIDE_ASM) == [('g', {'a0': 0})]
    (family, out), = arity.variants('s32 g(s32, s32);\n' + DIVIDE, 'f', DIVIDE_ASM)
    assert family == 'target_call_arity' and '    g(0);' in out and 's32 g(s32);' in out


SEARCH = '''s32 f(s32 arg0, s32 arg1) {
    s32 var_s0;

    var_s0 = arg0;
    if (var_s0 > 0x77) {
        var_s0 = 0x76;
    }
    if (arg1 < 0) {
loop_5:
        if (!(g(var_s0) & 0xFFFF)) {
            var_s0 -= 1;
            if (var_s0 <= 0) {
                var_s0 = 0x77;
            }
            goto loop_5;
        }
    } else {
loop_8:
        if (!(g(var_s0) & 0xFFFF)) {
            var_s0 += 1;
            if (var_s0 >= 0x77) {
                var_s0 = 0;
            }
            goto loop_8;
        }
    }
    return var_s0;
}
'''


def test_a_wrapping_counter_is_tested_before_its_step():
    # An N64 function's two search loops: 63.4%; tested first, the limit in a local, then as loops: exact.
    from decomprepair import wrapped_counter_repairs as w
    (family, tested), (_, held) = w.variants(SEARCH, 'f')
    assert family == 'wrapped_counter_step'
    assert '''            if (var_s0 > 0) {
                var_s0 -= 1;
            } else {
                var_s0 = 0x77;
            }''' in tested
    assert '''            if (var_s0 < 0x77) {
                var_s0 += 1;
            } else {
                var_s0 = 0;
            }''' in tested
    assert '{\n    s32 __repair_limit;\n    s32 var_s0;\n\n    __repair_limit = 0x77;\n    var_s0 = arg0;' in held
    assert '0x77' not in held.replace('__repair_limit = 0x77;', '')


def test_a_counter_that_does_not_wrap_is_left_alone():
    from decomprepair import wrapped_counter_repairs as w
    assert w.variants(SEARCH.replace('var_s0 -= 1;\n', 'var_s0 -= 2;\n').replace('var_s0 += 1;\n', 'var_s0 += 2;\n'),
                      'f') == []

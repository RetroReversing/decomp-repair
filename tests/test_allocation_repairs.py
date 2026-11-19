"""Pointer sums as integers, block copies as records, inverted guards and returned stored values."""
from decomprepair import guard_inversion_repairs as guard
from decomprepair import integer_sum_repairs as isum
from decomprepair import stored_return_value_repairs as ret
from decomprepair import word_block_copy_repairs as copy

LOOP = '''void f(void *arg0) {
    s32 var_s0;
    void *temp_s1;

    var_s0 = 0;
    do {
        temp_s1 = ((var_s0 & 0xFFFF) * 4) + arg0;
        g(M2C_FIELD(temp_s1, s32 *, 4));
        var_s0 += 1;
    } while ((u32) (var_s0 & 0xFFFF) < 9U);
}
'''


def test_pointer_sum_as_integers_both_orders():
    # Two N64 functions: `addu` operands as the game's (exact) only as integer arithmetic, index first.
    (family, first), (_, second) = isum.variants(LOOP, 'f')
    assert family == 'integer_pointer_sum'
    assert 'temp_s1 = (void *) ((((var_s0 & 0xFFFF) * 4)) + (s32) arg0);' in first
    assert 'temp_s1 = (void *) ((s32) arg0 + (((var_s0 & 0xFFFF) * 4)));' in second
    assert isum.variants(LOOP.replace('+ arg0', '+ var_s0'), 'f') == []  # not a pointer


COPY = '''void *f(void *arg1, void *temp_a0) {
    s32 temp_a1;

    temp_a1 = M2C_FIELD(arg1, s32 *, 8);
    M2C_FIELD(temp_a0, s32 *, 0xC) = (s32) M2C_FIELD(arg1, s32 *, 0);
    M2C_FIELD(temp_a0, s32 *, 0x10) = (s32) M2C_FIELD(arg1, s32 *, 4);
    M2C_FIELD(temp_a0, s32 *, 0x14) = temp_a1;
    g(temp_a0, temp_a1);
    return temp_a0;
}
'''


def test_word_copy_as_one_record():
    (family, out), = copy.variants(COPY, 'f')
    assert family == 'word_block_copy'
    assert 'typedef struct { s32 w[3]; } __repair_words3;' in out
    assert 'M2C_FIELD(temp_a0, __repair_words3 *, 0xC) = *(__repair_words3 *) ((s8 *) arg1 + 0x0);' in out
    assert 'g(temp_a0, M2C_FIELD(temp_a0, s32 *, 0x14));' in out and 'temp_a1 =' not in out
    assert copy.variants(COPY.replace('(arg1, s32 *, 4)', '(arg1, s32 *, 0x24)'), 'f') == []  # not consecutive


GUARD = '''s32 f(s32 arg0) {
    s32 var_v0;

    var_v0 = 0;
    if (D_8010086A) return var_v0;
    var_v0 = 1;
    D_800E09B8 = arg0;
    return var_v0;
}
'''


def test_guard_inverted_around_the_work():
    # An N64 function: 98% as a guard or as direct returns, exact inverted.
    (family, out), = guard.variants(GUARD, 'f')
    assert family == 'guard_inversion'
    assert '''    if (!(D_8010086A)) {
        var_v0 = 1;
        D_800E09B8 = arg0;
        return var_v0;
    }
    return var_v0;
}''' in out
    assert guard.variants(GUARD.replace('return var_v0;\n    var_v0 = 1;', 'g();\n    var_v0 = 1;'), 'f') == []


SEED = '''extern u32 D_800CFDF0;

void f(void) {
    s32 temp_v1;

    temp_v1 = D_800CFDF0 * 4;
    D_800CFDF0 = (u32) ((temp_v1 + 2) * (temp_v1 + 3)) >> 2;
}
'''
SEED_ASM = 'mflo       $v0\nsrl        $v0, $v0, 2\nlui        $at, %hi(D_800CFDF0)\njr         $ra\nsw         $v0, %lo(D_800CFDF0)($at)\n'
COUNTER = '''void f(void *arg0) {
    M2C_FIELD(arg0, f32 *, 4) = 0.0f;
    M2C_FIELD(arg0, s32 *, 0) = (s32) (M2C_FIELD(arg0, s32 *, 0) - 1);
}
'''
COUNTER_ASM = 'lw         $v0, ($a0)\naddiu      $v1, $v0, -1\nswc1       $f0, 4($a0)\njr         $ra\nsw         $v1, ($a0)\n'


def test_the_stored_value_is_returned():
    # An SDK random-number routine: 95.9% as void, exact returning the stored seed.
    (family, out), = ret.variants(SEED, 'f', SEED_ASM)
    assert family == 'stored_return_value'
    assert 'u32 f(void) {' in out and out.rstrip().endswith('>> 2;\n    return D_800CFDF0;\n}')
    assert ret.variants(SEED, 'f', SEED_ASM.replace('sw         $v0', 'sw         $v1')) == []


def test_the_counters_old_value_is_returned():
    # An N64 function at 99.7%: exact as `return field--;`.
    (family, out), = ret.variants(COUNTER, 'f', COUNTER_ASM)
    assert 's32 f(void *arg0) {' in out and '    return M2C_FIELD(arg0, s32 *, 0)--;\n}' in out
    assert ret.variants(COUNTER, 'f', COUNTER_ASM.replace('lw         $v0, ($a0)', 'lw         $v0, 8($a0)')) == []

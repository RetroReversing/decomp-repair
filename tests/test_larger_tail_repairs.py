"""Calls made in each arm, arguments passed from saved registers, loop addresses at their use, and an earlier
rewrite's result copies undone, each from an N64 function a whole deep pass left unimproved."""
from decomprepair import (
    loop_address_inline_repairs,
    result_debris_repairs,
    saved_register_argument_repairs,
    tail_call_arm_repairs,
)

ARMS = '''void f(void) {
    M2C_UNK *var_a1;
    s32 t;

    t = g();
    if (t != 1) {
        h(0x22);
        var_a1 = &D_1;
    } else {
        h(0x19);
        var_a1 = &D_2;
    }
    k(&D_0, var_a1, 0x3840);
    t += 1;
}
'''


def test_the_call_is_made_in_each_arm():
    (family, out), = tail_call_arm_repairs.variants(ARMS, 'f')
    assert family == 'call_into_arms'
    assert '        h(0x22);\n        k(&D_0, &D_1, 0x3840);\n    } else {' in out
    assert '        h(0x19);\n        k(&D_0, &D_2, 0x3840);\n    }\n    t += 1;' in out
    assert 'var_a1' not in out


def test_left_alone_when_the_variable_is_read_elsewhere():
    assert tail_call_arm_repairs.variants(ARMS.replace('    t += 1;', '    t += *var_a1;'), 'f') == []


SAVED = '''s32 g();
s32 h();

void f(void) {
    g(D_10, 0x1E);
    h(D_10);
}
'''
SAVED_ASM = '''/* 0 */  lui        $s2, %hi(D_10)
/* 4 */  addiu      $s2, $s2, %lo(D_10)
/* 8 */  lui        $s1, %hi(D_20)
/* c */  addiu      $s1, $s1, %lo(D_20)
/* 10 */  addu       $a0, $s2, $zero
/* 14 */  jal        g
/* 18 */  addiu      $a1, $zero, 0x1E
/* 1c */  addu       $a0, $s2, $zero
/* 20 */  addu       $a1, $s1, $zero
/* 24 */  jal        h
/* 28 */  nop
'''


def test_an_argument_passed_from_a_saved_register_is_added():
    (family, out), = saved_register_argument_repairs.variants(SAVED, 'f', SAVED_ASM)
    assert family == 'saved_register_argument'
    assert '    h(D_10, &D_20);' in out and '    g(D_10, 0x1E);' in out


def test_nothing_without_the_targets_moves():
    assert saved_register_argument_repairs.variants(SAVED, 'f', SAVED_ASM.replace('addu       $a1, $s1, $zero',
                                                                                  'addiu      $a1, $zero, 3')) == []


LOOP = '''void f(void *arg0) {
    void *var_a0;
    void *var_s0;

    var_s0 = M2C_FIELD(arg0, void **, 0x20);
    var_a0 = var_s0 + 0x24;
    do {
        g(var_a0, arg0);
        var_s0 = M2C_FIELD(var_s0, void **, 0);
        var_a0 = var_s0 + 0x24;
    } while (var_s0 != NULL);
}
'''


def test_the_loop_address_is_written_at_its_use():
    (family, out), = loop_address_inline_repairs.variants(LOOP, 'f')
    assert family == 'loop_address_inline'
    assert '        g(var_s0 + 0x24, arg0);' in out and 'var_a0' not in out


def test_left_alone_when_read_twice():
    assert loop_address_inline_repairs.variants(LOOP.replace('g(var_a0, arg0);', 'g(var_a0, var_a0);'), 'f') == []


DEBRIS = '''void f(void) {
    u8 var_s1;
u8 __repair_result_var_s1;
    void *temp_v0;

    var_s1 = 0;
    if (g() & 0xFFFF) {
        temp_v0 = h();
        if (temp_v0 != NULL) {
            __repair_result_var_s1 = M2C_FIELD(temp_v0, u8 *, 8);
        }
        D = __repair_result_var_s1;
    }
}
'''


def test_the_copy_is_undone_and_the_initializer_guarded():
    (_, undone), (family, guarded) = result_debris_repairs.variants(DEBRIS, 'f')
    assert family == 'result_debris'
    assert '__repair_result' not in undone and '            var_s1 = M2C_FIELD(temp_v0, u8 *, 8);' in undone
    assert '    if (g() & 0xFFFF) {\n        var_s1 = 0;\n        temp_v0 = h();' in guarded

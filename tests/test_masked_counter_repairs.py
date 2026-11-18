"""m2c's masked word counters and masked byte parameters, as the `u8` counter and parameter the source had."""
from decomprepair import masked_counter_repairs as m

SOURCE = '''void f(void *arg0, s8 arg1) {
    s32 var_s1;
    s32 var_v0;
    u32 temp_a1;

    if (arg0 != NULL) {
        M2C_FIELD(arg0, s8 *, 0x1F) = arg1;
        temp_a1 = arg1 & 0xFF;
        if (temp_a1 != 0) {
            g(arg0, temp_a1);
            return;
        }
        var_s1 = 0;
        if (temp_a1 < (u8) M2C_FIELD(arg0, u8 *, 0x19)) {
            var_v0 = 0 & 0xFF;
            do {
                h(M2C_FIELD(arg0, s32 *, 0) + (var_v0 * 0xC), M2C_FIELD(arg0, u8 *, 0x18) == var_v0);
                var_s1 += 1;
                var_v0 = var_s1 & 0xFF;
            } while ((u32) (var_s1 & 0xFF) < (u8) M2C_FIELD(arg0, u8 *, 0x19));
        }
    }
}
'''
LOOP = '''        for (var_s1 = 0; var_s1 < (u8) M2C_FIELD(arg0, u8 *, 0x19); var_s1++) {
            h(M2C_FIELD(arg0, s32 *, 0) + (var_s1 * 0xC), M2C_FIELD(arg0, u8 *, 0x18) == var_s1);
        }
    }
}'''


def test_both_together_then_each():
    # An N64 game (gcc 2.7.2): both together left 2 instructions of 44 different, either alone 32 or 41.
    (f1, both), (f2, loop), (f3, param) = m.variants(SOURCE, 'f')
    assert (f1, f2, f3) == ('masked_counter_loop', 'masked_counter_loop', 'byte_parameter_sign')
    assert 'void f(void *arg0, u8 arg1)' in both and 'temp_a1 = arg1;' in both and LOOP in both
    assert '    u8 var_s1;\n' in both and 'var_v0' not in both and 'do {' not in both
    assert 'void f(void *arg0, s8 arg1)' in loop and LOOP in loop
    assert 'void f(void *arg0, u8 arg1)' in param and 'do {' in param


def test_loop_needs_a_zero_entry_and_no_outside_reads():
    assert m.counter_loops(SOURCE.replace('if (temp_a1 != 0)', 'if (temp_a1 != 1)'), 'f') == []
    assert m.counter_loops(SOURCE.replace('            return;\n        }\n        var_s1', '        }\n        var_s1'), 'f') == []
    zero = SOURCE.replace('if (temp_a1 < (u8)', 'if (0 < (u8)')
    assert m.counter_loops(zero, 'f')
    assert m.counter_loops(SOURCE.replace('    }\n}\n', '    }\n    g(var_s1, 0);\n}\n'), 'f') == []
    # a different limit in the guard than in the loop test
    assert m.counter_loops(SOURCE.replace('if (temp_a1 < (u8) M2C_FIELD(arg0, u8 *, 0x19))',
                                          'if (temp_a1 < (u8) M2C_FIELD(arg0, u8 *, 0x1A))'), 'f') == []


def test_byte_parameter_only_when_every_use_is_a_byte():
    assert m.byte_parameters(SOURCE.replace('temp_a1 = arg1 & 0xFF;', 'temp_a1 = arg1;'), 'f') == []
    assert m.byte_parameters(SOURCE.replace('temp_a1 = arg1 & 0xFF;', 'temp_a1 = 1 + arg1 & 0xFF;'), 'f') == []
    called = SOURCE.replace('temp_a1 = arg1 & 0xFF;', 'temp_a1 = k(arg1 & 0xFF);')
    out = m.byte_parameters(called, 'f')[0][1]
    assert 'temp_a1 = k(arg1);' in out and 'u8 arg1' in out


def test_propose_finds_the_family():
    from decomprepair.propose import propose
    assert {p.family for p in propose(SOURCE, 'f').proposals
            if p.module == 'masked_counter_repairs'} == {'masked_counter_loop', 'byte_parameter_sign'}

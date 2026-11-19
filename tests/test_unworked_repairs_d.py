"""Search loops put right side out, unguarded masked counters, and parameters shaped as the target uses them."""
from decomprepair import masked_counter_repairs, parameter_shape_repairs, search_exit_loop_repairs

FOUND = '''void f(s32 arg0) {
    char *var_a1;
    s32 var_v1;

    var_v1 = 0;
    var_a1 = &D;
    G = arg0;
    H = 0;
    while (*(s16 *)var_a1 != arg0) {
        var_v1 += 1;
        var_a1 += 2;
        if (var_v1 >= 0x20U) {
            return;
        }
    }
    H = var_v1;
}
'''

SHARED = '''s32 f(s32 arg0, s32 arg1, s32 arg2) {
    s32 var_a3;
    s32 var_v0;
    u16 temp_v1;

    var_a3 = 1;
    var_v0 = 1 & 0xFF;
    for (;;) {
        temp_v1 = M2C_FIELD(((var_v0 * 2) + arg0), u16 *, 0x138);
        if ((temp_v1 & 0xFF) != (arg1 & 0xFF)) {
            var_a3 += 1;
            goto block_8;
        }
        if ((temp_v1 >> 8) == (arg2 & 0xFF)) {
            break;
        }
        var_a3 += 1;
block_8:
        var_v0 = var_a3 & 0xFF;
        if ((u32) (var_a3 & 0xFF) >= 0x1EU) {
            return 0;
        }
    }
    return 1;
}
'''


def test_the_found_case_goes_inside_the_loop():
    # An N64 search over 0x20 halfwords: 35% as m2c wrote it, exact so.
    (family, out), = search_exit_loop_repairs.variants(FOUND, 'f')
    assert family == 'found_inside_loop'
    assert '''    do {
        if (*(s16 *)var_a1 == arg0) {
            H = var_v1;
            return;
        }
        var_v1 += 1;
        var_a1 += 2;
    } while (var_v1 < 0x20U);
}''' in out


def test_the_shared_step_loop_and_then_its_counter():
    # An N64 search over 0x1E slots: 34%; 80% as a do/while, exact once the masked counter is a u8.
    (family, shaped), = search_exit_loop_repairs.variants(SHARED, 'f')
    assert family == 'shared_step_loop' and 'goto' not in shaped
    assert 'if (((temp_v1 & 0xFF) == (arg1 & 0xFF)) && ((temp_v1 >> 8) == (arg2 & 0xFF))) {\n            return 1;' in shaped
    assert '} while ((u32) (var_a3 & 0xFF) < 0x1EU);\n    return 0;' in shaped
    loops = [t for f, t in masked_counter_repairs.variants(shaped, 'f') if f == 'masked_counter_loop']
    assert loops and 'u8 var_a3;' in loops[0] and 'for (var_a3 = 1; var_a3 < 0x1E; var_a3++) {' in loops[0]
    assert 'var_v0' not in loops[0]


def test_the_unguarded_counter_needs_a_start_below_the_limit():
    shaped = search_exit_loop_repairs.variants(SHARED, 'f')[0][1]
    assert masked_counter_repairs.unguarded_loops(shaped.replace('var_a3 = 1;', 'var_a3 = 0x20;'), 'f') == []


def test_the_break_search_loop():
    source = '''s32 f(s32 *arg0, s32 arg1) {
    s32 i;
    s32 t;

    i = 0;
    for (;;) {
        t = i;
        i += 1;
        if (arg0[t] == arg1) {
            break;
        }
        if (i >= 8) {
            return -1;
        }
    }
    return t;
}
'''
    (family, out), = [v for v in search_exit_loop_repairs.variants(source, 'f') if v[0] == 'break_search_loop']
    assert '''    do {
        t = i;
        i += 1;
        if (arg0[t] == arg1) {
            return t;
        }
    } while (i < 8);
    return -1;''' in out


def test_left_alone_when_the_loop_has_more_to_it():
    assert search_exit_loop_repairs.variants(FOUND.replace('    H = var_v1;\n}', '    if (H) {\n        g();\n    }\n}'), 'f') == []
    assert search_exit_loop_repairs.variants(SHARED.replace('goto block_8;', 'goto block_9;'), 'f') == []


MASKED = '''s32 *f(s32 arg0) {
    u16 i;
    s32 *q;

    for (i = 0; i < N; i++) {
        q = T[i];
        if ((q != NULL) && ((arg0 & 0x1E000) == (*q & 0x1E000))) {
            return q;
        }
    }
    return NULL;
}
'''


def test_a_masked_parameter_is_masked_once_at_the_top():
    # An N64 search: 80% with the mask in the test, exact with `arg0 &= 0x1E000;` first.
    (family, out), = [v for v in parameter_shape_repairs.variants(MASKED, 'f') if v[0] == 'parameter_mask_hoist']
    assert '    s32 *q;\n\n    arg0 &= 0x1E000;\n    for' in out
    assert '((arg0) == (*q & 0x1E000))' in out or '(arg0 == (*q & 0x1E000))' in out
    assert parameter_shape_repairs.mask_hoist(MASKED.replace('return q;', 'return q + arg0;'), 'f') == []


def test_float_register_parameters():
    source = 'void f(void *arg0, M2C_UNK arg1, M2C_UNK arg2, f32 arg3) {\n    g(arg0);\n}\n'
    asm = 'addiu $sp, $sp, -0x30\nmtc1 $a1, $fs2\nmtc1 $a2, $fs0\njal g\nnop\n'
    (family, out), = parameter_shape_repairs.variants(source, 'f', asm)
    assert family == 'float_register_parameter'
    assert 'void f(void *arg0, f32 arg1, f32 arg2, f32 arg3)' in out
    assert parameter_shape_repairs.variants(source, 'f', 'jal g\nmtc1 $a1, $fs2\n') == []


def test_propose_finds_them():
    from decomprepair.propose import propose
    assert 'search_exit_loop_repairs' in {p.module for p in propose(FOUND, 'f').proposals}
    assert 'parameter_shape_repairs' in {p.module for p in propose(MASKED, 'f').proposals}

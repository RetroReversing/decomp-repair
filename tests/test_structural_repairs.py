"""Rewrites from near-miss N64 functions (gcc 2.7.2 -O2) a 10,000-variant deep pass couldn't improve. Each shape is
homemade; the docstrings of the modules say what each made exact."""
from decomprepair import (
    comma_flag_condition_repairs,
    compound_global_update_repairs,
    conditional_ternary_repairs,
    duplicate_return_node_repairs,
    field_load_hoist_repairs,
    flag_returns_repairs,
    float_zero_local_repairs,
    narrow_widening_repairs,
    narrowed_call_argument_repairs,
    reloaded_global_repairs,
    short_counter_loop_repairs,
    symbol_width_repairs,
    unknown32_float_repairs,
)


def texts(variants):
    return [text for _, text in variants]


def test_split_read_modify_write_collapses_interleaved_updates_together():
    source = """void f(u8 *p) {
    u8 *m;
    u8 a;
    u8 b;

    m = &D_8010A4C1;
    a = *m;
    b = D_8010A4C2;
    a = (a | 4) & ~1;
    b &= ~1;
    *m = a;
    D_8010A4C2 = b;
    g(m);
    a = *m;
    b = D_8010A4C2;
    a |= 1;
    b |= 1;
    *m = a;
    D_8010A4C2 = b;
    g(m);
}
"""
    found = [(family, text) for family, text in compound_global_update_repairs.variants(source, 'f')
             if family == compound_global_update_repairs.SPLIT]
    out = [text for _, text in found]
    # the second update collapsed as one child, the first left alone (one site alone moved nothing in the game)
    second = ('    g(m);\n    *m |= 1;\n    D_8010A4C2 |= 1;\n    g(m);')
    assert any(second in text and '    a = (a | 4) & ~1;' in text for text in out)
    # the load folded into the update while the store stays
    assert any('    b = D_8010A4C2;\n    a = (*m | 4) & ~1;\n    b &= ~1;\n    *m = a;' in text for text in out)
    assert any('    *m = (*m | 4) & ~1;\n    D_8010A4C2 &= ~1;' in text and second in text for text in out)


def test_split_read_modify_write_leaves_a_value_read_after_the_store():
    source = """s32 f(void) {
    u8 a;

    a = D_80100000;
    a |= 1;
    D_80100000 = a;
    return a;
}
"""
    out = texts(compound_global_update_repairs.split_variants(source, 'f'))
    assert out and all('return a;' in text and 'D_80100000 |= 1' not in text for text in out)


def test_narrow_widening_offers_each_narrow_local_and_parameter_as_s32():
    source = '''void f(void *arg0, s16 arg1) {
    s8 temp_s1;

    temp_s1 = M2C_FIELD(arg0, s8 *, 0xE);
    g();
    M2C_FIELD(arg0, s16 *, 0x7C) = arg1 + temp_s1;
}
'''
    out = texts(narrow_widening_repairs.variants(source, 'f'))
    assert any('void f(void *arg0, s32 arg1)' in t for t in out)
    assert any('    s32 temp_s1;' in t and 's16 arg1' in t for t in out)
    assert narrow_widening_repairs.variants(source.replace('s16 arg1', 's32 arg1').replace('s8 temp', 's32 temp'), 'f') == []
    two = source.replace('    s8 temp_s1;\n', '    s8 temp_s1;\n    s16 temp_a0;\n')
    assert any('    s32 temp_s1;\n    s32 temp_a0;' in t for t in texts(narrow_widening_repairs.variants(two, 'f')))


def test_unknown32_float_when_the_target_moves_the_field_through_the_fpu():
    source = '''void f(void) {
    M2C_UNK32 temp_fv0;

    temp_fv0 = M2C_FIELD(D, M2C_UNK32 *, 0x2B3C);
    M2C_FIELD(D, M2C_UNK32 *, 0x2B30) = temp_fv0;
}
'''
    (family, out), = unknown32_float_repairs.variants(source, 'f', 'lwc1       $fv0, 0x2B3C($v1)\n')
    assert family == 'unknown32_float' and 'M2C_UNK32' not in out.split('{', 1)[1] and 'f32 temp_fv0;' in out
    assert unknown32_float_repairs.variants(source, 'f', 'lw         $a0, 0x2B3C($v1)\n') == []


def test_symbol_widths_include_float_tables():
    source = '''void f(s32 i) {
    D_8 = *((M2C_UNK *)((s8 *)&D_800C46AC + (i * 0xE8))) * D_9;
}
'''
    out = texts(symbol_width_repairs.variants(source, 'f', 'lwc1       $fv0, %lo(D_800C46AC)($at)\n'))
    assert any('*((f32 *)((s8 *)&D_800C46AC' in t for t in out)


def test_narrowed_call_argument_passes_the_whole_word():
    source = '''M2C_UNK g(u16, u16);

void f(void *p) {
    g((u16) M2C_FIELD(p, s32 *, 0x14), M2C_FIELD(p, u16 *, 0x18));
}
'''
    (family, out), = narrowed_call_argument_repairs.variants(source, 'f')
    assert family == 'narrowed_call_argument'
    assert 'M2C_UNK g(s32, u16);' in out and 'g(M2C_FIELD(p, s32 *, 0x14), M2C_FIELD(p, u16 *, 0x18));' in out


def test_flag_returns_return_each_constant_where_it_is_set():
    source = '''s32 f(void) {
    s32 var_v0;

    var_v0 = 0;
    if (g() == 0x21) {
        register var_v0 = 0;
        if (h() == 5) {
            var_v0 = 1;
        }
    }
    return var_v0;
}
'''
    (family, out), = flag_returns_repairs.variants(source, 'f')
    assert family == 'flag_returns' and 'var_v0' not in out
    assert '            return 1;\n        }\n    }\n    return 0;\n}' in out
    busy = source.replace('            var_v0 = 1;\n        }', '            var_v0 = 1;\n        }\n        k();')
    assert flag_returns_repairs.variants(busy, 'f') == []


def test_float_zero_local_only_when_the_target_uses_the_fpu_zero():
    source = '''void f(void *arg0) {
    M2C_FIELD(arg0, f32 *, 8) = 0.0f;
    M2C_FIELD(arg0, f32 *, 4) = 0.0f;
}
'''
    (family, out), = float_zero_local_repairs.variants(source, 'f', 'mtc1       $zero, $fv0\n')
    assert family == 'float_zero_local' and out.count('= __repair_fzero;') == 2 and 'f32 __repair_fzero = 0.0f;' in out
    assert float_zero_local_repairs.variants(source, 'f', 'sw         $zero, 0x8($a0)\n') == []


def test_short_counter_loop_as_a_for_loop():
    source = '''void f(void) {
    s16 temp_v0;
    s32 var_s0;
    s32 var_a0;

    var_s0 = 0;
    g();
    var_a0 = 0 << 0x10;
    do {
        h(var_a0 >> 0x10, 2);
        temp_v0 = var_s0 + 1;
        var_s0 = temp_v0;
        var_a0 = var_s0 << 0x10;
    } while (temp_v0 < 4);
}
'''
    (family, out), = short_counter_loop_repairs.variants(source, 'f')
    assert family == 'short_counter_loop'
    assert '    for (temp_v0 = 0; temp_v0 < 4; temp_v0++) {\n        h(temp_v0, 2);\n    }\n' in out
    assert 'var_s0 = 0;' not in out and '<< 0x10' not in out


def test_duplicate_return_node_as_an_early_return():
    source = '''s32 f(s32 arg0, s32 arg1) {
    if (D != 0) {
        if (arg0 != -1) {
            if (arg1 > 0) {
                g(arg0, arg1 & 0xFF);
                return arg0;
            }
            h(arg0);
            goto block_5;
        }
        /* Duplicate return node #6. Try simplifying control flow for better match */
        return -1;
    }
block_5:
    return -1;
}
'''
    (family, out), = duplicate_return_node_repairs.variants(source, 'f')
    assert family == 'duplicate_return_node' and 'goto' not in out and 'block_5' not in out
    assert '        if (arg0 == -1) {\n            return -1;\n        }\n        if (arg1 > 0) {' in out
    assert duplicate_return_node_repairs.variants(source.replace('    return -1;\n}', '    return 0;\n}'), 'f') == []


def test_conditional_ternary():
    source = '''s32 f(s32 arg0) {
    s32 var_v0;

    var_v0 = arg0;
    if (arg0 < 0) {
        var_v0 = -var_v0;
    }
    return var_v0;
}
'''
    out = texts(conditional_ternary_repairs.variants(source, 'f'))
    assert '    return (arg0 >= 0) ? arg0 : -arg0;' in out[0] and 'var_v0' not in out[0]


def test_compound_global_update():
    source = '''u32 f(s32 arg0) {
    u32 var_v1;

    register temp_v0 = D_8010D368 - arg0;
    register var_v1 = temp_v0;
    D_8010D368 = temp_v0;
    return var_v1;
}
'''
    out = texts(compound_global_update_repairs.variants(source, 'f'))
    assert '    var_v1 = D_8010D368 -= arg0;\n    return var_v1;' in out[0]
    assert '    D_8010D368 -= arg0;\n    var_v1 = D_8010D368;' in out[1]


def test_comma_flag_condition_as_two_returns():
    source = '''s32 f(void *arg0, f32 arg2) {
    s32 var_v0;

    if (!(g(arg0) < 2.0f) || (var_v0 = 1, !(h(arg0) < arg2))) {
        var_v0 = 0;
    }
    return var_v0;
}
'''
    (family, out), = comma_flag_condition_repairs.variants(source, 'f')
    assert family == 'comma_flag_condition' and 'var_v0' not in out
    assert 'if ((g(arg0) < 2.0f) && (h(arg0) < arg2)) {\n        return 1;\n    }\n    return 0;' in out


def test_reloaded_global_when_every_mention_is_a_load():
    source = '''extern void *D_80109688;

void f(void) {
    if (D_80109688 != NULL) {
        M2C_FIELD(D_80109688, f32 *, 0x12C) = 1.0f;
    }
}
'''
    asm = 'lw         $v0, %lo(D_80109688)($v0)\nlw         $v0, %lo(D_80109688)($v0)\n'
    (family, out), = reloaded_global_repairs.variants(source, 'f', asm)
    assert family == 'reloaded_global' and 'extern void *volatile D_80109688;' in out
    assert reloaded_global_repairs.variants(source, 'f', asm.split('\n', 1)[0]) == []


def test_field_load_hoist():
    source = '''void f(void *arg0) {
    s32 temp_v1;

    temp_v1 = M2C_FIELD(arg0, s32 *, 0x60);
    if (temp_v1 & 0x400000) {
        M2C_FIELD(arg0, s32 *, 0x60) = temp_v1 & 0xFFBFFFFF;
        g(*M2C_FIELD(arg0, u8 **, 0x6C));
    }
}
'''
    (family, out), = field_load_hoist_repairs.variants(source, 'f')
    assert family == 'field_load_hoist' and 'u8 * __repair_hoisted;' in out
    assert '    __repair_hoisted = M2C_FIELD(arg0, u8 **, 0x6C);\n    if (temp_v1 & 0x400000) {' in out
    assert 'g(*__repair_hoisted);' in out

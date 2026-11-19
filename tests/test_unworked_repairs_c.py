"""Round-seven repairs: a global pointer tested and cleared through its address, and m2c's counted call loop."""
from decomprepair import counted_call_loop_repairs as loops
from decomprepair import symbol_base_repairs as bases

GLOBAL = '''extern void *D_800B5B14;

void f(void) {
    g();
    if (D_800B5B14 != NULL) {
        M2C_FIELD(D_800B5B14, s32 *, 0x60) = (s32) (M2C_FIELD(D_800B5B14, s32 *, 0x60) | 1);
        D_800B5B14 = NULL;
    }
}
'''


def test_the_field_reads_keep_naming_the_global():
    # An N64 function was 80.2% with every use through the pointer, exact with only the test and the clear through it.
    texts = [t for _, t in bases.variants(GLOBAL, 'f')]
    kept = [t for t in texts if 'M2C_FIELD(D_800B5B14, s32 *, 0x60)' in t and '(*__base_D_800B5B14) = NULL;' in t]
    assert kept and 'if ((*__base_D_800B5B14) != NULL)' in kept[0]
    assert any('M2C_FIELD((*__base_D_800B5B14), s32 *, 0x60)' in t for t in texts)  # the all-through form stays


def test_no_kept_form_when_nothing_reads_through_it():
    source = GLOBAL.replace('''        M2C_FIELD(D_800B5B14, s32 *, 0x60) = (s32) (M2C_FIELD(D_800B5B14, s32 *, 0x60) | 1);\n''', '')
    texts = [t for _, t in bases.variants(source, 'f')]
    assert all('M2C_FIELD(D_800B5B14' not in t for t in texts)


LOOP = '''s32 f(u8, s32);
extern u8 D;

s32 g(s32 arg0) {
    s32 var_s0;
    u8 var_a0;

    if (D != 0) {
        var_s0 = 0;
        var_a0 = 0 & 0xFFFF;
loop_2:
        var_s0 += 1;
        if (f(var_a0, arg0) == 0) {
            var_a0 = var_s0 & 0xFFFF;
            if ((u32) (var_s0 & 0xFFFF) >= 4U) {
                return 0;
            }
            goto loop_2;
        }
        return 1;
    }
    return 2;
}
'''


def test_the_counted_call_loop():
    # An N64 function at 80.4%: exact as this loop, with the callee's guessed u8 parameter the counter's u16.
    (family, out), = loops.variants(LOOP, 'g')
    assert family == 'counted_call_loop'
    assert '''        for (var_s0 = 0; var_s0 < 4; var_s0++) {
            if (f(var_s0, arg0) != 0) {
                return 1;
            }
        }
        return 0;
''' in out
    assert 'u16 var_s0;' in out and 'var_a0' not in out and 's32 f(u16, s32);' in out


def test_left_alone_otherwise():
    assert loops.variants(LOOP.replace('    return 2;', '    return var_a0;'), 'g') == []  # the copy is used after
    assert loops.variants(LOOP.replace('>= 4U', '>= 4U || var_s0 == 2'), 'g') == []


def test_a_two_test_guard_nested():
    from decomprepair import nested_guard_repairs as guards
    source = '''s32 f(s32 slot, s32 arg1) {
    if ((slot != -1) && (slot >= 0)) {
        g(slot);
        return 1;
    }
    return 0;
}
'''
    (family, out), = guards.variants(source, 'f')
    assert family == 'nested_guard'
    assert '''    if ((slot != -1)) {
        if ((slot >= 0)) {
            g(slot);
            return 1;
        }
    }
    return 0;''' in out
    assert guards.variants(source.replace('    return 0;', '    else { return 2; }\n    return 0;').replace(
        '        return 1;\n    }\n', '        return 1;\n    }'), 'f') == []  # an else arm
    assert guards.variants(source.replace('&& (slot >= 0)', '&& (slot >= 0) && (slot < 9)'), 'f') == []


def test_from_the_forms_a_deep_pass_keeps():
    # A deep pass stores goto_backward_loop's form of the loop and this family's all-through form when they score
    # better; both repairs must start from those too.
    loop = LOOP.replace('''loop_2:
        var_s0 += 1;
        if (f(var_a0, arg0) == 0) {
            var_a0 = var_s0 & 0xFFFF;
            if ((u32) (var_s0 & 0xFFFF) >= 4U) {
                return 0;
            }
            goto loop_2;
        }
        return 1;''', '''        for (;;) {
            var_s0 += 1;
            if (f(var_a0, arg0) != 0) {
                break;
            }
            var_a0 = var_s0 & 0xFFFF;
            if ((u32) (var_s0 & 0xFFFF) >= 4U) {
                return 0;
            }
        }
        return 1;''')
    (_, out), = loops.variants(loop, 'g')
    assert 'for (var_s0 = 0; var_s0 < 4; var_s0++) {' in out and 'var_a0' not in out
    through = [t for _, t in bases.variants(GLOBAL, 'f') if 'M2C_FIELD((*__base_D_800B5B14)' in t][0]
    texts = [t for _, t in bases.variants(through, 'f')]
    assert texts and all(t.count('void **__base_D_800B5B14;') == 1 for t in texts)
    assert any('M2C_FIELD(D_800B5B14, s32 *, 0x60)' in t and '(*__base_D_800B5B14) = NULL;' in t for t in texts)

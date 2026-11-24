"""Deferred stores, byte-indexed tables of unknown type, and global pointers held in a local."""
from decomprepair import (
    counter_loop_repairs,
    deferred_store_repairs,
    global_pointer_local_repairs,
    unknown_table_index_repairs,
)

MATRIX = '''void f(void *arg0, void *arg1, void *arg2) {
    f32 temp_ft1;
    f32 temp_ft2;

    temp_ft2 = M2C_FIELD(arg1, f32 *, 0);
    temp_ft1 = M2C_FIELD(arg1, f32 *, 4);
    M2C_FIELD(arg2, f32 *, 0) = (f32) ((M2C_FIELD(arg0, f32 *, 0) * temp_ft2) + (M2C_FIELD(arg0, f32 *, 4) * temp_ft1));
    M2C_FIELD(arg2, f32 *, 4) = (f32) ((M2C_FIELD(arg0, f32 *, 8) * temp_ft2) + (M2C_FIELD(arg0, f32 *, 0xC) * temp_ft1));
}
'''


def test_sums_first_then_the_stores():
    # Four N64 matrix-times-vector functions: 54.8%, exact with one of these two.
    (family, kept), (_, inlined) = deferred_store_repairs.variants(MATRIX, 'f')
    assert family == 'deferred_stores'
    assert kept.index('__repair_store_1 = ') < kept.index('M2C_FIELD(arg2, f32 *, 0) = __repair_store_0;')
    assert 'temp_ft2' not in inlined and inlined.count('M2C_FIELD(arg1, f32 *, 0)') == 2
    assert '    M2C_FIELD(arg2, f32 *, 4) = __repair_store_1;\n}' in inlined


def test_stores_of_plain_values_are_left_alone():
    plain = 'void f(void *a, s32 b) {\n    M2C_FIELD(a, s32 *, 0) = b;\n    M2C_FIELD(a, s32 *, 4) = b;\n}\n'
    assert deferred_store_repairs.variants(plain, 'f') == []


TABLES = '''extern M2C_UNK D_80109DC8;
extern M2C_UNK D_800E097E;

void f(void) {
    s32 temp_v1;
    s32 var_a0;

    var_a0 = 0;
    do {
        temp_v1 = (var_a0 & 0xFFFF) * 2;
        if (*(temp_v1 + &D_80109DC8) != 0) {
            *(temp_v1 + &D_800E097E) = 0;
        }
        var_a0 += 1;
    } while ((u32) (var_a0 & 0xFFFF) < 4U);
}
'''
ASM = 'lui        $t2, %hi(D_80109DC8)\naddiu      $t2, $t2, %lo(D_80109DC8)\nlhu        $v0, 0x0($v0)\n'


def test_a_byte_indexed_table_as_the_array_it_is():
    # An N64 function clearing parallel u16 tables: exact after u16_counter_loop and this.
    looped = counter_loop_repairs.variants(TABLES, 'f')[0][1]
    (family, unsigned), (_, signed) = unknown_table_index_repairs.variants(looped, 'f', ASM)
    assert family == 'unknown_table_index'
    assert '((u16 *) &D_80109DC8)[__repair_i] != 0' in unsigned and 'temp_v1' not in unsigned
    assert '((s16 *) &D_800E097E)[__repair_i] = 0;' in signed
    # a scale that isn't the width the target uses for the symbol
    assert unknown_table_index_repairs.variants(looped, 'f', 'lw         $v0, %lo(D_80109DC8)($at)\n'
                                                'lw         $v0, %lo(D_800E097E)($at)\n') == []


GLOBAL = '''void f(void) {
    g(&D_80107EA8);
    if (D_800BD554 != NULL) {
        M2C_FIELD(D_800BD554, s32 *, 0x10) = (s32) ((M2C_FIELD(D_800BD554, s32 *, 0x10) & ~0xFF) | 1);
    }
    h(&D_80107EA8, D_800BD554);
}
'''


def test_a_tested_global_pointer_held_in_a_local():
    # An N64 function at 94.3%: exact with the global read once.
    (family, out), = global_pointer_local_repairs.variants(GLOBAL, 'f')
    assert family == 'global_pointer_local'
    assert '    __repair_D_800BD554 = D_800BD554;\n    if (__repair_D_800BD554 != NULL) {' in out
    assert 'h(&D_80107EA8, __repair_D_800BD554);' in out


def test_left_alone_when_a_call_could_change_it():
    assert global_pointer_local_repairs.variants(GLOBAL.replace('    h(&D', '    k();\n    h(&D'), 'f') == []
    # a store before the test: only the tested block reads the local, and the call after it reads the global again
    (_, out), = global_pointer_local_repairs.variants(GLOBAL.replace('    g(&D', '    D_800BD554 = 0;\n    g(&D'), 'f')
    assert 'D_800BD554 = 0;' in out and 'h(&D_80107EA8, D_800BD554);' in out
    assert 'if (__repair_D_800BD554 != NULL)' in out
    assert global_pointer_local_repairs.variants(
        GLOBAL.replace('    }\n    h(', '        D_800BD554 = 0;\n    }\n    h('), 'f') == []


SWITCH = '''void f(void *arg0) {
    if (arg0 != NULL) {
        switch (M2C_FIELD(arg0, u16 *, 0x78)) {
        case 0x38:
        case 0x37:
            g(M2C_FIELD(arg0, s32 *, 0x6C), arg0);
            return;
        case 0x39:
            h(M2C_FIELD(arg0, s32 *, 0x6C), arg0);
            break;
        }
    }
}
'''


def test_stacked_case_labels_get_their_own_body():
    # An N64 function: gcc's compare tree tested 0x38 and 0x37 apart, the bodies merged later. 76.4% -> 91.4% (exact
    # once a stray `case 0: break;` an earlier rewrite added is gone too).
    from decomprepair import case_split_repairs
    (family, out), = case_split_repairs.variants(SWITCH, 'f')
    assert family == 'split_case_labels'
    assert out.count('g(M2C_FIELD(arg0, s32 *, 0x6C), arg0);\n            return;') == 2
    assert '        case 0x38:\n            g(' in out and '        case 0x37:\n            g(' in out


def test_a_body_with_a_label_or_block_is_left_alone():
    from decomprepair import case_split_repairs
    labelled = SWITCH.replace('            g(M2C_FIELD', 'block_7:\n            g(M2C_FIELD')
    assert case_split_repairs.variants(labelled, 'f') == []
    blocked = SWITCH.replace('            g(M2C_FIELD(arg0, s32 *, 0x6C), arg0);\n            return;',
                             '            if (arg0) {\n                g(arg0);\n            }\n            return;')
    assert case_split_repairs.variants(blocked, 'f') == []

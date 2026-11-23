"""A table-lookup function with an arm per kind of cell: the arms' pointer sums, the byte copy, the load order and the
zero arm (KMC GCC 2.7.2). The source is a small invented lookup with the shape of m2c's draft of such a function."""
from decomprepair import registry
from decomprepair import tile_arm_chains as p

SOURCE = '''#define M2C_FIELD(expr, type_ptr, offset) (*(type_ptr)((s8 *)(expr) + (offset)))
extern char D_80001000[];
extern char D_80002000[];

s32 cell(s32 arg0, s32 arg1, s32 arg2) {
    s32 temp_a2;
    s32 var_v0_3;
    u32 temp_t0;
    u8 var_v1;
    u8 *var_v0;
    void *temp_v1;
    void *var_v1_2;

    temp_a2 = arg2 & 0xFF;
    if (temp_a2 != 0xFF) {
        temp_t0 = arg0 & 0xFF;
        if (temp_t0 < 0x40U) {
            temp_v1 = ((arg1 & 0xFF) * 0x24) + ((temp_a2 * 0x240) + D_80001000) + (arg0 & 0x1F);
            var_v1 = M2C_FIELD(temp_v1, u8 *, 0x20);
            var_v0_3 = M2C_FIELD(temp_v1, u8 *, 0) << 7;
            goto block_19;
        }
        var_v1_2 = ((arg1 & 0xFF) * 0x24) + ((temp_a2 * 0x240) + D_80001000);
        temp_v1 = var_v1_2 + (arg0 & 0xFE);
        var_v1 = M2C_FIELD(temp_v1, u8 *, 1);
        var_v0_3 = M2C_FIELD(temp_v1, u8 *, 0) << 7;
        goto block_19;
    }
    temp_t0 = arg0 & 0xFF;
    if (temp_t0 < 0x40U) {
        temp_v1 = ((arg1 & 0xFF) * 0x24) + D_80002000 + (arg0 & 0x1F);
        var_v1 = M2C_FIELD(temp_v1, u8 *, 0x20);
        var_v0_3 = M2C_FIELD(temp_v1, u8 *, 0) << 7;
block_19:
        return var_v1 | var_v0_3;
    }
    if ((u32) ((arg0 - 0x60) & 0xFF) < 6U) {
        return 0;
    }
    var_v0 = ((arg1 & 0xFF) * 0x24) + D_80002000 + temp_t0;
    return *var_v0 << 7;
}
'''


def texts(source, family):
    return [text for name, text in p.variants(source, 'cell') if name == family]


def test_the_bank_arms_take_the_index_term_first_with_the_row_product_in_a_scope():
    [scoped, plain] = texts(SOURCE, 'bank_index_first')
    assert ('{ u8 *bp = D_80001000; u8 *bank; do { bank = bp + temp_a2 * 0x240; } while (0); '
            'var_v1_2 = (u8 *)((arg1 & 0xFF) * 0x24) + (int)bank; }') in scoped
    assert ('temp_v1 = (u8 *)((arg1 & 0xFF) * 0x24) + (int)bank + (arg0 & 0x1F); }') in scoped
    assert 'bank = bp + temp_a2 * 0x240; var_v1_2' in plain and 'do { bank' not in plain
    assert 'D_80001000 +' not in scoped.replace('u8 *bp = D_80001000', '')


def test_the_table_arms_keep_their_table_address_in_a_local():
    [scoped, _] = texts(SOURCE, 'bank_index_first')
    assert '{ u8 *bp = D_80002000; temp_v1 = bp + (arg1 & 0xFF) * 0x24 + (arg0 & 0x1F); }' in scoped
    assert '{ u8 *bp = D_80002000; var_v0 = bp + (arg1 & 0xFF) * 0x24 + temp_t0; }' in scoped


def test_only_declared_arrays_are_tables():
    source = SOURCE.replace('extern char D_80002000[];', 'extern char D_80002000;')
    [scoped, _] = texts(source, 'bank_index_first')
    assert 'D_80002000 + (arg0 & 0x1F)' in scoped


def test_one_arm_at_a_time():
    [scoped, _] = texts(SOURCE, 'bank_index_first')
    off = texts(scoped, 'bank_arm_scope')
    assert len(off) == 2 and all(t.count('do { bank') == 1 for t in off)
    back = texts(off[0], 'bank_arm_scope')
    assert any(t.count('do { bank') == 2 for t in back)
    forms = texts(scoped, 'table_arm_scope')
    assert len(forms) == 2 * 4  # two table arms, four spellings each
    assert any('u32 bb; u8 *bp; bb = (arg1 & 0xFF); bp = D_80002000; var_v0 = bp + bb * 0x24 + temp_t0;' in t for t in forms)
    assert any('do { temp_v1 = sm + (arg0 & 0x1F); } while (0);' in t for t in forms)
    assert any('u32 bb; do { bb = (arg1 & 0xFF); } while (0); var_v0 = bp + bb * 0x24 + temp_t0;' in t for t in forms)


def test_a_parameter_masked_twice_is_read_through_a_byte_copy():
    [text] = texts(SOURCE, 'byte_entry_copy')
    assert text.count('temp_t0 = arg0_byte & 0xFF;') == 2
    assert 'u8 arg0_byte;' in text and 'arg0_byte = arg0;' in text
    assert text.index('arg0_byte = arg0;') > text.index('void *var_v1_2;')
    assert text.index('arg0_byte = arg0;') < text.index('temp_a2 = arg2 & 0xFF;')
    assert 'arg2_byte' not in text


def test_the_loads_come_before_the_shift():
    source = SOURCE.replace('var_v1 = M2C_FIELD(temp_v1, u8 *, 0x20);\n            var_v0_3 = M2C_FIELD(temp_v1, u8 *, 0) << 7;',
                            'var_v1 = M2C_FIELD(temp_v1, u8 *, 1);\n            var_v0_3 = M2C_FIELD(temp_v1, u8 *, 0) << 7;')
    [text, *others] = texts(source, 'load_shift_split')
    assert ('var_v0_3 = M2C_FIELD(temp_v1, u8 *, 0);\n            var_v1 = M2C_FIELD(temp_v1, u8 *, 1);\n'
            '            var_v0_3 = var_v0_3 << 7;') in text
    # each pair alone, and with its two statements the other way round
    assert text.count('var_v0_3 = var_v0_3 << 7;') >= 1 and any(other.count('var_v0_3 = var_v0_3 << 7;') == 1 for other in others)
    assert any('var_v0_3 = M2C_FIELD(temp_v1, u8 *, 0) << 7;\n            var_v1 = M2C_FIELD(temp_v1, u8 *, 1);' in other
               for other in others)


def test_the_zero_arm_moves_to_the_end():
    [text] = texts(SOURCE, 'zero_arm_inversion')
    assert 'if ((u32) ((arg0 - 0x60) & 0xFF) >= 6U) {\n    var_v0 =' in text
    assert text.rstrip().endswith('return *var_v0 << 7;\n    }\n    return 0;\n}')
    assert text.count('return 0;') == 1


def test_a_loop_after_the_zero_arm_is_left_alone():
    source = SOURCE.replace('return *var_v0 << 7;', 'while (temp_t0) { temp_t0 -= 1; }\n    return *var_v0 << 7;')
    assert texts(source, 'zero_arm_inversion') == []


def test_all_of_it_at_once_is_one_child():
    [text] = texts(SOURCE, 'tile_arm_chains')
    assert 'do { bank = bp + temp_a2 * 0x240; } while (0);' in text
    assert 'arg0_byte & 0xFF' in text and '>= 6U' in text
    assert text.count('return 0;') == 1


def test_a_function_without_the_shape_has_no_children():
    assert p.variants('s32 f(s32 a)\n{\n    return a + 1;\n}\n', 'f') == []


def test_volatile_is_left_alone():
    assert p.variants(SOURCE.replace('u8 var_v1;', 'volatile u8 var_v1;'), 'cell') == []


def test_the_module_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'tile_arm_chains')
    assert repair.families == p.FAMILIES and registry.problems(repair) == []


def test_the_joining_return_is_copied_into_the_arms_that_jump_to_it():
    source = SOURCE.replace('''    var_v0 = ((arg1 & 0xFF) * 0x24) + D_80002000 + temp_t0;
    return *var_v0 << 7;''', '''    var_v0 = ((arg1 & 0xFF) * 0x24) + D_80002000 + temp_t0;
block_27:
    return *var_v0 << 7;''').replace('''        goto block_19;
    }
    temp_t0''', '''        var_v0 = ((arg1 & 0xFF) * 0x24) + ((temp_a2 * 0x240) + D_80001000);
        goto block_27;
    }
    temp_t0''')
    text = texts(source, 'shared_return_split')[-1]
    assert 'var_v0_b = ((arg1 & 0xFF) * 0x24) + D_80002000 + temp_t0;\n    return *var_v0_b << 7;' in text
    assert 'var_v0_b;' in text
    assert 'goto block_27' not in text and '        return *var_v0 << 7;' in text


def test_a_goto_is_replaced_by_the_run_it_jumps_to():
    source = SOURCE.replace('''        goto block_19;
    }
    temp_t0''', '''        goto block_18;
    }
    temp_t0''').replace('''block_19:
        return''', '''block_18:
        temp_v1 = var_v1_2 + (arg0 & 0xFE);
        var_v1 = M2C_FIELD(temp_v1, u8 *, 1);
block_19:
        return''')
    [text] = texts(source, 'label_run_copy')
    assert 'temp_v1 = var_v1_2 + (arg0 & 0xFE);\n        var_v1 = M2C_FIELD(temp_v1, u8 *, 1);\n        goto block_19;' in text
    assert 'goto block_18' not in text and 'block_18:' in text


def test_the_later_value_takes_the_dead_locals_name():
    source = SOURCE.replace('    u32 temp_t0;', '    u32 temp_t0;\n    u32 temp_b;').replace(
        'temp_t0 = arg0 & 0xFF;\n    if (temp_t0 < 0x40U) {\n        temp_v1 = ((arg1 & 0xFF) * 0x24) + D_80002000',
        'temp_b = arg0 & 0xFF;\n    if (temp_b < 0x40U) {\n        temp_v1 = ((arg1 & 0xFF) * 0x24) + D_80002000').replace(
        'D_80002000 + temp_t0;', 'D_80002000 + temp_b;')
    [reused] = texts(source, 'dead_local_reuse')
    assert 'temp_b' not in reused and 'u32 temp_a2_b;' not in reused
    assert reused.count('temp_a2 = arg0 & 0xFF;') == 1 and 'temp_a2_b' not in reused

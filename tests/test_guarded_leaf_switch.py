from decomprepair import guarded_leaf_switch as gls

DRAFT = '''extern u8 D_80001000;
extern M2C_UNK D_80002000;
extern s16 D_80003000;

void func_80000000(void) {
    s32 i;

    i = 0;
    do {
        *(&D_80002000 + i) = 0xFF;
        i += 1;
    } while (i < 6);
    if (D_80001000 == 1) {
        if (D_80003000 != 2) {
            if (D_80003000 >= 3) {
                if (D_80003000 != 3) {
                    return;
                }
                M2C_FIELD(&D_80002000, s8 *, 0) = 3;
            } else {
                if (D_80003000 != D_80001000) {
                    return;
                }
                M2C_FIELD(&D_80002000, u8 *, 1) = 1;
            }
        } else {
            if (i) {
                return;
            }
            M2C_FIELD(&D_80002000, u8 *, 2) = 2;
        }
    }
}
'''


def test_arrays_and_guard_constant_together():
    family, text = gls.variants(DRAFT, 'func_80000000')[0]
    assert family == 'unknown_byte_array'
    assert 'extern u8 D_80002000[];' in text and 'D_80002000[i] = 0xFF;' in text
    assert 'D_80002000[0] = 3;' in text and 'D_80003000 != 1)' in text


def test_tree_of_guarded_leaves_becomes_a_switch():
    _, arrays = gls.variants(DRAFT, 'func_80000000')[0]
    switches = [text for family, text in gls.variants(arrays, 'func_80000000') if family == 'guarded_leaf_switch']
    first = switches[0]
    assert 'switch (D_80003000) {' in first
    assert first.index('case 1:') < first.index('case 2:') < first.index('case 3:')
    assert 'D_80002000[1] = 1;\n    break;' in first and 'if (i) {' in first


def test_code_after_the_tree_keeps_it():
    _, arrays = gls.variants(DRAFT, 'func_80000000')[0]
    followed = arrays.rstrip()[:-1] + '    D_80001000 = 0;\n}\n'
    assert not [f for f, _ in gls.variants(followed, 'func_80000000') if f == 'guarded_leaf_switch']


def test_a_table_that_is_also_indexed_is_not_split_into_variables():
    from decomprepair.m2cfix import refine_draft

    refined = refine_draft(DRAFT, 'func_80000000', '')
    assert 'D_80002001' not in refined and 'extern char D_80002000[];' in refined

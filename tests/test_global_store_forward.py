"""A temporary stored to a global and read back is written as the global."""
from decomprepair import global_store_forward as g

DRAFT = '''extern u32 D_800E1550;
extern s8 D_800E1554;
extern s8 D_800E1555;

void f(void *arg0, s32 arg1, u32 arg3) {
    s32 temp_v1_2;
    u8 temp_v0_2;
    u32 temp_v0;
    void *temp_v1;

    D_800E1550 = 0;
    do {
        temp_v1_2 = 1 << M2C_FIELD(arg0, s32 *, 4);
        temp_v0_2 = 1 << D_800E1550;
        D_800E1555 = temp_v0_2;
        D_800E1554 = temp_v1_2;
        if (arg1 & temp_v0_2) {
            temp_v1 = M2C_FIELD(arg0, void **, 0);
            M2C_FIELD(temp_v1, u8 *, 0) |= temp_v1_2;
        }
        temp_v0 = D_800E1550 + 1;
        D_800E1550 = temp_v0;
    } while (temp_v0 < arg3);
}
'''


def test_both_temporaries_are_forwarded_in_one_child():
    both = [t for f, t in g.variants(DRAFT, 'f') if f == 'global_store_forward_unsigned'][-1]
    assert 'D_800E1554 = 1 << M2C_FIELD(arg0, s32 *, 4);' in both
    assert 'D_800E1555 = 1 << D_800E1550;' in both
    assert 'if (arg1 & D_800E1555)' in both
    assert '|= D_800E1554;' in both
    assert 'temp_v1_2' not in both and 'temp_v0_2' not in both
    assert 'extern u8 D_800E1555;' in both and 'extern u8 D_800E1554;' in both
    assert 'temp_v0 = D_800E1550 + 1;' in both


def test_global_type_is_kept_in_the_plain_child():
    plain = [t for f, t in g.variants(DRAFT, 'f') if f == 'global_store_forward'][-1]
    assert 'extern s8 D_800E1555;' in plain


def test_a_name_m2c_reuses_is_forwarded_only_up_to_its_next_assignment():
    reused = DRAFT.replace('        temp_v0 = D_800E1550 + 1;',
                           '        temp_v1_2 = M2C_FIELD(arg0, s32 *, 4);\n        M2C_FIELD(arg0, s32 *, 4) = temp_v1_2 + 1;\n        temp_v0 = D_800E1550 + 1;')
    both = [t for f, t in g.variants(reused, 'f') if f == 'global_store_forward_unsigned'][-1]
    assert '        temp_v1_2 = M2C_FIELD(arg0, s32 *, 4);' in both
    assert 'temp_v1_2 + 1' in both
    assert 'D_800E1554 = 1 << M2C_FIELD(arg0, s32 *, 4);' in both


def test_an_assignment_that_reads_the_old_value_or_no_store_is_left_alone():
    reads = DRAFT.replace('        temp_v0 = D_800E1550 + 1;', '        temp_v1_2 = temp_v1_2 + 1;\n        temp_v0 = D_800E1550 + 1;')
    assert not [t for f, t in g.variants(reads, 'f') if 'D_800E1554 = 1 <<' in t]
    assert g.variants('void f(void) { int a; a = 1; }', 'f') == []

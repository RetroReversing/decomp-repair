"""symbol_stack_block_copy on a made-up name picker in m2c's shape (no game's code)."""
from decomprepair.registry import declared
from decomprepair.symbol_stack_block_copy import FAMILY, variants

DRAFT = '''extern M2C_UNK D_80001000;
extern M2C_UNK D_80001010;

void pick(s32 arg0) {
    s32 sp20[2];
    s16 sp28;                                       /* compiler-managed */
    s8 sp2A;
    s8 sp2C;
    M2C_UNK sp40;

    if (arg0 == 0) {
        sp20[0] = M2C_FIELD(&D_80001000, s32 *, 0);
        sp20[1] = M2C_FIELD(&D_80001000, s32 *, 4);
        sp28 = M2C_FIELD(&D_80001000, s16 *, 8);
        sp2A = M2C_FIELD(&D_80001000, s8 *, 0xA);
    } else {
        sp20[0] = M2C_FIELD(&D_80001010, s32 *, 0);
        sp20[1] = M2C_FIELD(&D_80001010, s32 *, 4);
        sp28 = M2C_FIELD(&D_80001010, s32 *, 8);
        sp2C = M2C_FIELD(&D_80001010, s8 *, 0xC);
    }
    open(&sp40, sp20);
}
'''


def test_each_run_is_one_copy_into_an_array_up_to_the_next_local():
    [(family, child)] = variants(DRAFT, 'pick')
    assert family == FAMILY
    assert 's32 sp20[8];' in child
    assert '__builtin_memcpy(sp20, &D_80001000, 11);' in child
    assert '__builtin_memcpy(sp20, &D_80001010, 13);' in child
    for local in ('sp28', 'sp2A', 'sp2C'):
        assert local not in child
    assert 'open(&sp40, sp20);' in child


def test_a_stored_local_that_is_read_elsewhere_is_left_alone():
    assert variants(DRAFT.replace('open(&sp40, sp20);', 'open(&sp40, sp20, sp28);'), 'pick') == []


def test_a_run_with_a_gap_is_not_a_block():
    assert variants(DRAFT.replace('s32 *, 4);', 's32 *, 8);'), 'pick') == []


def test_it_is_registered():
    assert any(FAMILY in repair.families for repair in declared())

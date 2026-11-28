"""stride_typed_symbol_arrays, switch_bias_unfold and member_update_reread: homemade drafts."""
from decomprepair import member_update_reread, stride_typed_arrays, switch_bias_unfold

DRAFT = """extern M2C_UNK gTotals;
extern M2C_UNK gFlags;
extern M2C_UNK gExtra;
extern M2C_UNK gColors;
void update(void *self) {
    M2C_UNK *var_v0;
    s32 *temp_v1;
    s32 index;

    index = M2C_FIELD(self, u8 *, 2);
    M2C_FIELD(self, u8 *, 4) = *(u8 *)(index + &gColors);
    M2C_FIELD(self, u8 *, 5) = M2C_FIELD((index + &gColors), u8 *, 1);
    switch (index) {
    case 0:
        *((M2C_FIELD(self, u8 *, 0) * 4) + &gTotals) = 6;
        var_v0 = &gFlags;
block_1:
        *(M2C_FIELD(self, u8 *, 0) + var_v0) = 1;
        break;
    case 1:
        temp_v1 = (M2C_FIELD(self, u8 *, 0) * 4) + &gTotals;
        *temp_v1 += 0x64;
        var_v0 = &gExtra;
        goto block_1;
    }
}
"""


def test_every_symbol_is_typed_by_its_stride_in_one_child():
    child = stride_typed_arrays.variants(DRAFT, 'update')[0][1]
    assert 'extern s32 gTotals[];' in child
    assert 'extern u8 gFlags[];' in child and 'extern u8 gExtra[];' in child
    assert 'extern u8 gColors[];' in child
    assert 'gTotals[M2C_FIELD(self, u8 *, 0)] = 6;' in child
    assert 'gTotals[M2C_FIELD(self, u8 *, 0)] += 0x64;' in child
    assert '= gColors[index];' in child and '= gColors[index + 1];' in child
    # the pointer picked between two tables before one store is written out on both paths
    assert 'gFlags[M2C_FIELD(self, u8 *, 0)] = 1;' in child
    assert 'gExtra[M2C_FIELD(self, u8 *, 0)] = 1;' in child
    assert 'var_v0' not in child and 'goto' not in child


def test_refined_char_arrays_are_typed_too():
    source = """extern char D_80000010[];
extern s32 gTotals;
void update(s32 i) {
    *((i * 4) + &gTotals) = *(i + D_80000010);
}
"""
    child = stride_typed_arrays.variants(source, 'update')[0][1]
    assert 'extern u8 D_80000010[];' in child and 'gTotals[i] = D_80000010[i];' in child


def test_a_symbol_with_two_strides_is_left_alone():
    source = """extern M2C_UNK gMixed;
void update(s32 i) {
    *((i * 4) + &gMixed) = 0;
    *(i + &gMixed) = 0;
}
"""
    assert stride_typed_arrays.variants(source, 'update') == []


BIASED = """void update(s32 type) {
    u32 var_v1;

    var_v1 = type - 1;
    if (type == 0x11) {
        type = roll();
        var_v1 = type - 1;
    }
    switch (var_v1) {
    case 0:
    case 5:
        a();
        break;
    case 2:
        b();
        break;
    }
}
"""


def test_switch_on_a_biased_copy_is_written_on_the_value():
    [(family, child)] = switch_bias_unfold.variants(BIASED, 'update')
    assert family == 'switch_bias_unfold'
    assert 'var_v1' not in child and 'switch (type) {' in child
    assert 'case 1:' in child and 'case 6:' in child and 'case 3:' in child


def test_a_copy_that_goes_stale_is_not_unfolded():
    stale = BIASED.replace('    switch (var_v1)', '    type = roll();\n    switch (var_v1)')
    assert switch_bias_unfold.variants(stale, 'update') == []


def test_update_through_a_pointer_member_copy_rereads_the_member():
    source = """void update(void *self) {
    Part *temp_a1;

    temp_a1 = M2C_FIELD(self, Part **, 0x48);
    if (temp_a1 != 0) {
        M2C_FIELD(self, u16 *, 0) = 1;
        M2C_FIELD(temp_a1, s32 *, 0x1C) = (s32) (M2C_FIELD(temp_a1, s32 *, 0x1C) + 0x100);
    }
}
"""
    [(family, child)] = member_update_reread.variants(source, 'update')
    assert 'M2C_FIELD(M2C_FIELD(self, Part **, 0x48), s32 *, 0x1C) += 0x100;' in child

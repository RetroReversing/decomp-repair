from decomprepair import symbol_field_array

SOURCE = '''extern M2C_UNK D_800FA198;
extern M2C_UNK D_80072AA0;
extern M2C_UNK D_8006DF24;

void func(void) {
    M2C_FIELD(&D_800FA198, M2C_UNK **, 0) = &D_80072AA0;
    M2C_FIELD(&D_800FA198, M2C_UNK **, 4) = &D_80072AA0;
    M2C_FIELD(&D_800FA198, M2C_UNK **, 0x50) = &D_80072AA0;
    use(&D_800FA198, M2C_FIELD(&D_8006DF24, s32 *, 0), M2C_FIELD(&D_8006DF24, u8 *, 3));
}
'''


def test_table_becomes_an_array():
    (family, child), = symbol_field_array.variants(SOURCE, 'func')
    assert family == 'symbol_field_array'
    assert 'extern M2C_UNK *D_800FA198[];' in child
    assert 'D_800FA198[0] = &D_80072AA0;' in child
    assert 'D_800FA198[20] = &D_80072AA0;' in child
    assert 'use(&D_800FA198, M2C_FIELD(&D_8006DF24, s32 *, 0)' in child


def test_bare_use_or_mixed_types_are_left_alone():
    assert not symbol_field_array.variants(SOURCE.replace('use(&D_800FA198,', 'use(D_800FA198,'), 'func')
    assert not symbol_field_array.variants(SOURCE.replace('M2C_UNK **, 4)', 's32 *, 4)'), 'func')

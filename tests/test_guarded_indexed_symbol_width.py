from decomprepair.symbol_width_repairs import FAMILY, guarded_indexed_variants

SOURCE = '''extern s32 slots;
int f(int index) {
    if ((*((s32 *) (((s8 *) (&slots)) + (index * 24)))) == 0)
        return 1;
    return 0;
}'''
ASM = 'lbu $v0, %lo(slots)($v0)'


def test_narrows_the_load_cast_without_changing_index_scaling():
    [(family, child)] = guarded_indexed_variants(SOURCE, 'f', ASM)
    assert family == FAMILY
    assert child == SOURCE.replace('*((s32 *)', '*((u8 *)')


def test_requires_matching_symbol_width_and_a_zero_test():
    assert not guarded_indexed_variants(SOURCE, 'f', ASM.replace('slots', 'other'))
    assert not guarded_indexed_variants(SOURCE, 'f', ASM+'\nlw $v0, %lo(slots)($v0)')
    assert not guarded_indexed_variants(SOURCE.replace('== 0', '== 1'), 'f', ASM)

from decomprepair import offset_symbol_split

ASM = '''
lui        $at, %hi(D_80100000 + 0x8)
sh         $zero, %lo(D_80100000 + 0x8)($at)
lui        $at, %hi(D_80100000 + 0xA)
sh         $v0, %lo(D_80100000 + 0xA)($at)
lui        $at, %hi(D_80100000 + 0xC)
sb         $v0, %lo(D_80100000 + 0xC)($at)
'''

SOURCE = '''extern u8 D_80100000[];
void f(void)
{
    *((s16 *) (((u8 *) D_80100000) + 0x8)) = 0;
    *(s16 *)(D_80100000 + 0xA) = 7;
    D_80100000[0xC] = 0;
}
'''


def test_each_addressed_offset_becomes_its_own_global():
    (family, child), = offset_symbol_split.variants(SOURCE, 'f', ASM)
    assert family == 'offset_symbol_split'
    assert 'D_80100008 = 0;' in child and 'D_8010000A = 7;' in child and 'D_8010000C = 0;' in child
    assert 'extern s16 D_80100008;' in child and 'extern u8 D_8010000C;' in child
    assert child.index('extern s16 D_80100008;') < child.index('void f(')


def test_field_macro_and_other_offsets():
    source = SOURCE.replace('*((s16 *) (((u8 *) D_80100000) + 0x8)) = 0;', 'M2C_FIELD(D_80100000, s16 *, 0x8) = 0;')
    (_, child), = offset_symbol_split.variants(source + '\n', 'f', ASM)
    assert 'D_80100008 = 0;' in child
    # an offset the target does not address by itself stays
    other = SOURCE.replace('0xC]', '0xD]')
    (_, child), = offset_symbol_split.variants(other, 'f', ASM)
    assert 'D_80100000[0xD] = 0;' in child


def test_nothing_without_the_target_or_with_one_access():
    assert offset_symbol_split.variants(SOURCE, 'f', '') == []
    one = 'extern u8 D_80100000[];\nvoid f(void)\n{\n    D_80100000[0xC] = 0;\n}\n'
    assert offset_symbol_split.variants(one, 'f', ASM) == []

from decomprepair.indexed_store_width import variants

ASM = 'addiu $v0, $zero, 0x19\nsh $v0, %lo(D_800BE210)($at)\n'


def test_a_word_store_into_a_table_scaled_by_two_becomes_a_halfword_store():
    source = 'void f(s32 temp_s1) {\n    *(s32 *)((temp_s1 * 2) + D_800BE210) = 0x19;\n}\n'
    assert variants(source, 'f', ASM) == [('indexed_store_width', source.replace('s32 *', 's16 *'))]


def test_shift_scale_unsigned_constant_and_one_child_each():
    source = ('void f(s32 i) {\n    *(s32 *)((i << 1) + D_A) = 0x8000;\n    *((u32 *)(D_B + i * 2)) = 3;\n}\n')
    found = variants(source, 'f', ASM)
    assert 'u16 *)((i << 1)' in found[0][1] and 's16 *)(D_B' in found[0][1] and len(found) == 3


def test_an_unscaled_store_needs_the_target_to_have_no_word_stores():
    source = 'void f(s32 i) {\n    *(s32 *)(i + D_A) = 3;\n}\n'
    assert variants(source, 'f', ASM)
    assert variants(source, 'f', ASM + 'sw $v0, 4($a0)\n') == []
    assert variants(source, 'f', ASM + 'sw $ra, 4($sp)\n')


def test_nothing_without_sh_a_big_constant_or_a_non_constant_value():
    source = 'void f(s32 i) {\n    *(s32 *)((i * 2) + D_A) = 0x19;\n}\n'
    assert variants(source, 'f', 'sw $v0, 0($a0)\n') == []
    assert variants('void f(s32 i) {\n    *(s32 *)((i * 2) + D_A) = 0x19999;\n}\n', 'f', ASM) == []
    assert variants('void f(s32 i, s32 v) {\n    *(s32 *)((i * 2) + D_A) = v;\n}\n', 'f', ASM) == []

from decomprepair.pointer_table_deref import variants

ASM = """/* 0 */  lui        $a0, %hi(D_TABLE)
addu       $a0, $a0, $v0
lw         $a0, %lo(D_TABLE)($a0)
addiu      $v1, $zero, 0x15
sh         $v1, 0xA($a0)
lui        $v1, %hi(D_TABLE)
addu       $v1, $v1, $v0
lw         $v1, %lo(D_TABLE)($v1)
sb         $v0, 0x9($v1)
jr         $ra
"""
SOURCE = """extern u8 D_TABLE[];
void f(s32 t) {
    *(s16 *)(D_TABLE + t + 0xA) = 0x15;
    *((s8 *) ((D_TABLE + t) + 9)) = 0x78;
    *(s16 *)(D_TABLE + t + 0x40) = 1;
}
"""


def test_the_offsets_read_through_a_loaded_word_go_through_the_pointer():
    [(family, child)] = variants(SOURCE, 'f', ASM)
    assert family == 'pointer_table_deref'
    assert '*(s16 *)(*(u8 **)(D_TABLE + t) + 0xA) = 0x15;' in child
    assert '*((s8 *) (*(u8 **)(D_TABLE + t) + 9)) = 0x78;' in child
    assert '*(s16 *)(D_TABLE + t + 0x40) = 1;' in child


def test_no_pointer_load_or_a_scaled_table_is_left_alone():
    assert not variants(SOURCE, 'f', 'sh $v1, 0xA($a0)\n')
    assert not variants(SOURCE.replace('extern u8 D_TABLE[];', 'extern s16 D_TABLE[];'), 'f', ASM)

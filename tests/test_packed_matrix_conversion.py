import pytest

from decomprepair import packed_matrix_conversion as repair

ASM = '''
move $t0, $a1
addiu $t1, $t0, 32
move $t3, $zero
lui $at, 0x4780
mtc1 $at, $f10
lui $t4, 0xFFFF
move $t2, $a0
.Lrows:
move $a3, $zero
move $a2, $t2
.Lpairs:
lwc1 $f2, 0($a2)
mul.s $f2, $f2, $f10
lwc1 $f4, 4($a2)
mul.s $f4, $f4, $f10
addiu $a2, $a2, 8
addiu $a3, $a3, 1
trunc.w.s $f6, $f2
mfc1 $a0, $f6
trunc.w.s $f2, $f4
mfc1 $a1, $f2
and $v0, $a0, $t4
srl $v1, $a1, 16
or $v0, $v0, $v1
sw $v0, 0($t0)
addiu $t0, $t0, 4
sll $a0, $a0, 16
and $a0, $a0, $t4
andi $a1, $a1, 0xFFFF
or $a0, $a0, $a1
sw $a0, 0($t1)
slti $v0, $a3, 2
bnez $v0, .Lpairs
addiu $t1, $t1, 4
addiu $t3, $t3, 1
slti $v0, $t3, 4
bnez $v0, .Lrows
addiu $t2, $t2, 16
jr $ra
nop
'''
DRAFT = '''
void convert(void *src, s32 *dst) {
    f32 scale_right;
    f32 scale_left;
    s32 *whole;
    s32 *fraction;
    s32 left;
    s32 right;
    s32 pair;
    s32 row;
    void *sample;
    void *row_start;

    whole = dst;
    fraction = whole + 0x20;
    row = 0;
    row_start = src;
    do {
        pair = 0;
        sample = row_start;
    again:
        scale_left = M2C_FIELD(sample, f32 *, 0) * 65536.0f;
        scale_right = M2C_FIELD(sample, f32 *, 4) * 65536.0f;
        sample += 8;
        pair += 1;
        left = (s32) scale_left;
        right = (s32) scale_right;
        *whole = (left & 0xFFFF0000) | ((u32) right >> 0x10);
        whole += 4;
        *fraction = ((left << 0x10) & 0xFFFF0000) | (right & 0xFFFF);
        fraction += 4;
        if (pair < 2) {
            goto again;
        }
        row += 1;
        row_start += 0x10;
    } while (row < 4);
}
'''


@pytest.mark.parametrize('source', [
    DRAFT,
    DRAFT.replace('s32 *whole;', 'char *whole;').replace('s32 *fraction;', 'char *fraction;')
         .replace('*whole =', '*(s32 *)whole =').replace('*fraction =', '*(s32 *)fraction =')
         .replace('row = 0;\n    row_start = src;', 'row_start = src;\n    row = 0;'),
])
def test_recover_row_pair_indexing_and_in_order_packed_stores(source):
    result = repair.rewrite(source, 'convert', ASM)
    assert 'void convert(void *src, s32 *dst)' in result
    assert 'float (*__repair_matrix_rows)[4] = (float (*)[4])src;' in result
    assert '(u8 *)dst + 0x20' in result
    assert '__repair_matrix_row < 4' in result
    assert '__repair_matrix_pair < 2' in result
    assert result.index('*(__repair_matrix_integer++)') < result.index('*(__repair_matrix_fraction++)')


@pytest.mark.parametrize('asm', [
    ASM.replace('bnez $v0, .Lrows', 'bnez $v0, .Lpairs'),
    ASM.replace('sw $a0, 0($t1)', 'sw $a0, 0($t0)'),
    ASM.replace('lui $at, 0x4780', 'lui $at, 0x4700'),
    ASM.replace('addiu $t2, $t2, 16', 'addiu $t2, $t2, 32'),
])
def test_requires_the_target_layout_and_conversion(asm):
    assert repair.rewrite(DRAFT, 'convert', asm) is None


def test_leaves_a_different_source_conversion_and_conflicting_macro_alone():
    assert repair.rewrite(DRAFT.replace('scale_right;', 'scale_right + 1;'), 'convert', ASM) is None
    assert repair.rewrite(DRAFT, 'convert', ASM, '#define __repair_matrix_rows matrix') is None

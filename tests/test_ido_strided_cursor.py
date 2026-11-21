from decomprepair.draft_call_recovery import variants
from decomprepair.ido_strided_cursor import applies, rewrite

HALF_DRAFT = '''
void clear(void *out) {
    s32 i;
    void *p;
    p = out;
    i = 0;
    do {
        i += 4;
        M2C_FIELD(p, s16 *, 2) = 0;
        M2C_FIELD(p, s16 *, 4) = 0;
        M2C_FIELD(p, s16 *, 6) = 0;
        p += 8;
        M2C_FIELD(p, s16 *, -8) = 0;
    } while (i != 8);
}
'''
HALF_ASM = '''
or $v1, $a0, $zero
addiu $a0, $zero, 0x8
or $v0, $zero, $zero
.Lloop:
addiu $v0, $v0, 0x4
sh $zero, 2($v1)
sh $zero, 4($v1)
sh $zero, 6($v1)
addiu $v1, $v1, 8
bne $v0, $a0, .Lloop
sh $zero, -8($v1)
jr $ra
nop
'''
WORD_DRAFT = '''
void clear(void *out) {
    s32 i;
    void *p;
    M2C_FIELD(out, s8 *, 0x99) = 1;
    M2C_FIELD(out, s32 *, 0x38) = 0;
    M2C_FIELD(out, s32 *, 0x3C) = 0;
    p = out + 8;
    i = 2;
    do {
        i += 4;
        M2C_FIELD(p, s32 *, 0x38) = 0;
        M2C_FIELD(p, s32 *, 0x3C) = 0;
        M2C_FIELD(p, s32 *, 0x40) = 0;
        M2C_FIELD(p, s32 *, 0x44) = 0;
        p += 0x10;
    } while (i != 0xE);
}
'''
WORD_ASM = '''
addiu $t6, $zero, 1
sb $t6, 0x99($a0)
sw $zero, 0x38($a0)
sw $zero, 0x3c($a0)
addiu $v1, $a0, 8
addiu $a0, $zero, 0xE
addiu $v0, $zero, 2
.Lloop:
addiu $v0, $v0, 4
sw $zero, 56($v1)
sw $zero, 60($v1)
sw $zero, 64($v1)
sw $zero, 68($v1)
bne $v0, $a0, .Lloop
addiu $v1, $v1, 16
jr $ra
nop
'''
MATRIX_DRAFT = '''
void copy(f32 *src, void *dst) {
    f32 *input;
    f32 *inrow;
    f32 cell;
    s32 row;
    s32 col;
    void *output;
    void *outrow;
    row = 0;
    outrow = dst;
    inrow = src;
    do {
        col = 0;
        output = outrow;
        input = inrow;
inner:
        cell = *input;
        col += 1;
        output += 4;
        input += 4;
        M2C_FIELD(output, f32 *, -4) = cell;
        if (col != 3) { goto inner; }
        row += 1;
        outrow += 0x10;
        inrow += 0x10;
    } while (row != 3);
}
'''
MATRIX_ASM = '''
or $v0, $zero, $zero
or $a2, $a1, $zero
or $a3, $a0, $zero
addiu $t0, $zero, 3
.Louter:
or $v1, $zero, $zero
or $a0, $a2, $zero
or $a1, $a3, $zero
.Linner:
lwc1 $f4, 0($a1)
addiu $v1, $v1, 1
addiu $a0, $a0, 4
addiu $a1, $a1, 4
bne $v1, $t0, .Linner
swc1 $f4, -4($a0)
addiu $v0, $v0, 1
addiu $a2, $a2, 16
bne $v0, $t0, .Louter
addiu $a3, $a3, 16
jr $ra
nop
'''


def test_ido_halfword_clear_retains_typed_steps_and_backedge_store():
    assert applies(HALF_ASM)
    [(family, fixed)] = variants(HALF_DRAFT, 'clear', HALF_ASM, '', 'ido-7.1')
    assert family == 'ido_unrolled_halfword_clear'
    assert 'for (i = 0, p = out; i != 8;)' in fixed
    assert 'p[-4] = 0;' in fixed
    assert not rewrite(HALF_DRAFT, 'clear', HALF_ASM.replace('sh $zero, -8($v1)', 'nop'))
    assert not variants(HALF_DRAFT, 'clear', HALF_ASM, '', 'gcc-2.7.2-kmc')


def test_ido_word_clear_retains_its_prototype_and_same_line_setup():
    [(family, fixed)] = rewrite(WORD_DRAFT, 'clear', WORD_ASM, 'extern void clear(void *);')
    assert family == 'ido_unrolled_word_clear'
    assert 'void clear(void *out)' in fixed
    assert 'i = 2; p = (char *)out + 8; do {' in fixed
    assert '*(int *)(p + 68) = 0;' in fixed


def test_ido_strided_float_copy_restores_both_row_carriers():
    [(family, fixed)] = rewrite(MATRIX_DRAFT, 'copy', MATRIX_ASM)
    assert family == 'ido_strided_float_copy'
    assert 'float *src, float *dst' in fixed
    assert fixed.index('float *__m2c_step_dest') < fixed.index('float *__m2c_step_source')
    assert '__m2c_step_dest += 4;' in fixed
    assert not rewrite(MATRIX_DRAFT, 'copy', MATRIX_ASM.replace('bne $v1, $t0, .Linner', 'bne $v1, $t0, .Louter'))

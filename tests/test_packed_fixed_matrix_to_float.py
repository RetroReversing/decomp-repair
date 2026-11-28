from decomprepair import packed_fixed_matrix_to_float as repair

ASM = '''
glabel convert
addu       $t0, $a1, $zero
addiu      $t1, $t0, 0x20
addu       $t3, $zero, $zero
lui        $t4, (0xFFFF0000 >> 16)
lui        $at, %hi(D_scale)
lwc1       $ft0, %lo(D_scale)($at)
addu       $t2, $a0, $zero
.Lrows:
addu       $a3, $zero, $zero
addu       $a2, $t2, $zero
.Lpairs:
lw         $v1, 0x0($t0)
lw         $a1, 0x0($t1)
addiu      $t1, $t1, 0x4
and        $a0, $v1, $t4
srl        $v0, $a1, 16
or         $a0, $a0, $v0
sll        $v1, $v1, 16
mtc1       $a0, $fv1
cvt.s.w    $fv1, $fv1
mul.s      $fv1, $fv1, $ft0
and        $v1, $v1, $t4
andi       $a1, $a1, 0xFFFF
or         $v1, $v1, $a1
mtc1       $v1, $fv0
cvt.s.w    $fv0, $fv0
mul.s      $fv0, $fv0, $ft0
addiu      $t0, $t0, 0x4
addiu      $a3, $a3, 0x1
slti       $v0, $a3, 0x2
swc1       $fv1, 0x0($a2)
swc1       $fv0, 0x4($a2)
bnez       $v0, .Lpairs
addiu      $a2, $a2, 0x8
addiu      $t3, $t3, 0x1
slti       $v0, $t3, 0x4
bnez       $v0, .Lrows
addiu      $t2, $t2, 0x10
jr         $ra
nop
endlabel convert
'''
DRAFT = '''extern f32 D_scale;

void convert(void *dst, s32 *src) {
    s32 *whole;
    u32 *fraction;
    s32 word;
    u32 part;
    s32 pair;

    whole = src;
    fraction = whole + 0x20;
    pair = 0;
loop:
    word = *whole;
    part = *fraction;
    M2C_FIELD(dst, f32 *, 0) = (f32) ((word & 0xFFFF0000) | (part >> 0x10)) * D_scale;
    M2C_FIELD(dst, f32 *, 4) = (f32) (((word << 0x10) & 0xFFFF0000) | (part & 0xFFFF)) * D_scale;
    pair += 1;
    if (pair < 2) {
        goto loop;
    }
}
'''
INLINE = '''void convert(float *out, unsigned int a, unsigned int b) {
    int i;

    for (i = 0; i < 4; i++) {
        out[0] = (f32) (s32) ((a & 0xFFFF0000) | (b >> 16)) * (1.0f / 65536.0f);
        out[1] = (f32) (s32) (((a << 16) & 0xFFFF0000) | (b & 0xFFFF)) * (1.0f / 65536.0f);
        out += 2;
    }
}
'''


def test_the_measured_target_writes_the_loop_under_the_drafts_signature():
    [child] = [text for family, text in repair.variants(DRAFT, 'convert', ASM) if family == repair.MATRIX_FAMILY]
    assert 'void convert(void *dst, s32 *src) {' in child
    assert 'float (*__repair_fixed_rows)[4] = (float (*)[4]) dst;' in child
    assert '__repair_fixed_integer = (unsigned int *) src;' in child
    assert child.count('(1.0f / 65536.0f)') == 2 and 'goto' not in child
    assert child.index('__repair_fixed_second =') < child.index('(float) (int) __repair_fixed_first')


def test_another_target_scale_or_signature_gets_no_matrix_child():
    assert repair.recover(DRAFT, 'convert', ASM.replace('andi       $a1, $a1, 0xFFFF\n', '')) is None
    assert repair.recover(DRAFT, 'convert', ASM, {'D_scale': 0x3F800000}) is None
    assert repair.recover(DRAFT, 'convert', ASM, {'D_scale': 0x37800000}) is not None
    assert repair.recover(DRAFT.replace('void convert(', 's32 convert('), 'convert', ASM) is None


def test_both_converted_words_are_set_before_the_first_conversion():
    [(family, child)] = repair.variants(INLINE, 'convert')
    assert family == repair.PAIR_FAMILY
    assert ('        staged_word0 = (a & 0xFFFF0000) | (b >> 16);\n'
            '        staged_word1 = ((a << 16) & 0xFFFF0000) | (b & 0xFFFF);\n'
            '        out[0] = (f32) (s32) staged_word0 * (1.0f / 65536.0f);\n'
            '        out[1] = (f32) (s32) staged_word1 * (1.0f / 65536.0f);\n') in child
    assert 's32 staged_word0;\n    s32 staged_word1;' in child


def test_memory_reads_taken_addresses_and_written_names_stay_inline():
    assert repair.pairs(INLINE.replace('(b >> 16)', '(*out >> 16)'), 'convert') == []
    assert repair.pairs(INLINE.replace('int i;', 'int i;\n    use(&a);'), 'convert') == []
    assert repair.pairs(INLINE.replace('out[0] =', 'b ='), 'convert') == []

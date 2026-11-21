from decomprepair import draft_call_recovery, ido_matrix_copy, kmc_cartridge_io

READ_ASM = '''
addiu $sp, $sp, -32
sw $s1, 20($sp)
addu $s1, $a0, $zero
sw $s0, 16($sp)
addu $s0, $a1, $zero
bnez $s0, .Lcheck
sw $ra, 24($sp)
lui $a0, %hi(file_name)
addiu $a0, $a0, %lo(file_name)
lui $a1, %hi(error_text)
addiu $a1, $a1, %lo(error_text)
jal report_error
addiu $a2, $zero, 44
.Lcheck:
lui $v0, (0xA4600010 >> 16)
ori $v0, $v0, (0xA4600010 & 0xFFFF)
lw $v0, 0($v0)
andi $v0, $v0, 2
beqz $v0, .Lready
lui $v1, (0xA4600010 >> 16)
ori $v1, $v1, (0xA4600010 & 0xFFFF)
.Lpoll:
lw $v0, 0($v1)
andi $v0, $v0, 2
bnez $v0, .Lpoll
nop
.Lready:
lui $v0, %hi(base)
lw $v0, %lo(base)($v0)
lui $v1, %hi(window)
or $v0, $v0, $s1
or $v0, $v0, $v1
lw $v0, %lo(window)($v0)
sw $v0, 0($s0)
addu $v0, $zero, $zero
lw $ra, 24($sp)
lw $s1, 20($sp)
lw $s0, 16($sp)
jr $ra
addiu $sp, $sp, 32
'''
READ_C = '''
s32 f(s32 offset, s32 *out) {
    if (out == NULL) {
        report_error(&file_name, &error_text, 44);
    }
    if (*(s32 *)0xA4600010 & 2) {
        do {
        } while (*(void *)0xA4600010 & 2);
    }
    *out = *(base | offset | (s32) &window);
    return 0;
}
'''


def test_mapped_read_retains_assertion_and_requires_the_resolved_window():
    resolve = {'window': 0xA0000000}.get
    [(family, result)] = draft_call_recovery.variants(READ_C, 'f', READ_ASM, '', 'gcc-2.7.2-kmc', resolve=resolve)
    assert family == kmc_cartridge_io.FAMILY
    assert 'report_error(&file_name, &error_text, 44)' in result
    assert '_m2c_cart_offset = offset;' in result
    assert 'while (*(volatile u32 *)0xA4600010U & 2U)' in result
    assert '*(s32 *)((base | _m2c_cart_offset) | 0xA0000000U)' in result
    assert not kmc_cartridge_io.rewrite(READ_C, 'f', READ_ASM, resolve={'window': 0x80000000}.get)
    assert not kmc_cartridge_io.rewrite(READ_C, 'f', READ_ASM.replace('bnez $v0, .Lpoll', 'bnez $v0, .Lready'),
                                       resolve=resolve)


MATRIX_ASM = '''
or $v0, $zero, $zero
or $a2, $a0, $zero
addiu $a3, $zero, 4
.Lrow:
or $v1, $a1, $zero
lwc1 $ft0, 0($v1)
addiu $a1, $a1, 4
or $v1, $a1, $zero
swc1 $ft0, 0($a2)
lwc1 $ft1, 0($v1)
addiu $a1, $a1, 4
or $v1, $a1, $zero
swc1 $ft1, 4($a2)
lwc1 $ft2, 0($v1)
addiu $a1, $a1, 4
or $v1, $a1, $zero
swc1 $ft2, 8($a2)
lwc1 $ft3, 0($v1)
addiu $v0, $v0, 1
addiu $a1, $a1, 4
addiu $a2, $a2, 16
bne $v0, $a3, .Lrow
swc1 $ft3, -4($a2)
jr $ra
or $v0, $a0, $zero
'''
MATRIX_C = '''
void *f(void *dst, void *src) {
    s32 row;
    void *b;
    void *c;
    void *r;
    void *w;
    r = src;
    row = 0;
    w = dst;
    do {
        b = r + 4;
        M2C_FIELD(w, f32 *, 0) = (f32) M2C_FIELD(r, f32 *, 0);
        c = b + 4;
        M2C_FIELD(w, f32 *, 4) = (f32) M2C_FIELD(r, f32 *, 4);
        M2C_FIELD(w, f32 *, 8) = (f32) M2C_FIELD(b, f32 *, 4);
        row += 1;
        r = c + 4 + 4;
        w += 0x10;
        M2C_FIELD(w, f32 *, -4) = (f32) M2C_FIELD(c, f32 *, 4);
    } while (row != 4);
    return dst;
}
'''


def test_matrix_copy_keeps_the_two_loop_headers_on_the_same_line():
    [(family, result)] = draft_call_recovery.baseline_variants(MATRIX_C, 'f', MATRIX_ASM, '', 'ido-7.1')
    assert family == ido_matrix_copy.FAMILY
    assert 'f32 *f(f32 (*dst)[4], f32 *src)' in result
    assert '++) { for (' in result
    assert '_m2c_copy_word = src++;' in result
    assert not ido_matrix_copy.rewrite(MATRIX_C, 'f', MATRIX_ASM.replace('swc1 $ft3, -4', 'swc1 $ft3, 0'))
    assert not ido_matrix_copy.rewrite(MATRIX_C, 'f', MATRIX_ASM, 'void *f(void *, void *);')


DMA_ASM = '''
addiu $sp, $sp, -32
sw $s0, 16($sp)
addu $s0, $a0, $zero
sw $s1, 20($sp)
addu $s1, $a1, $zero
lui $v0, (0xA4600010 >> 16)
ori $v0, $v0, (0xA4600010 & 0xFFFF)
sw $ra, 28($sp)
sw $s2, 24($sp)
lw $v0, 0($v0)
addu $a0, $a2, $zero
andi $v0, $v0, 2
beqz $v0, .Lready
addu $s2, $a3, $zero
lui $v1, (0xA4600010 >> 16)
ori $v1, $v1, (0xA4600010 & 0xFFFF)
.Lpoll:
lw $v0, 0($v1)
andi $v0, $v0, 2
bnez $v0, .Lpoll
nop
.Lready:
jal translate
nop
lui $a2, (0xA4600004 >> 16)
ori $a2, $a2, (0xA4600004 & 0xFFFF)
lui $a1, (0x1FFFFFFF >> 16)
lui $v1, %hi(base)
lw $v1, %lo(base)($v1)
ori $a1, $a1, (0x1FFFFFFF & 0xFFFF)
lui $a0, %hi(dram)
sw $v0, %lo(dram)($a0)
or $v1, $v1, $s1
and $v1, $v1, $a1
sw $v1, 0($a2)
beqz $s0, .Lwrite
addiu $v0, $zero, 1
beq $s0, $v0, .Lread
lui $v1, (0xA4600008 >> 16)
j .Lexit
addiu $v0, $zero, -1
.Lwrite:
lui $v1, (0xA460000C >> 16)
j .Lcommit
ori $v1, $v1, (0xA460000C & 0xFFFF)
.Lread:
ori $v1, $v1, (0xA4600008 & 0xFFFF)
.Lcommit:
addiu $v0, $s2, -1
sw $v0, 0($v1)
addu $v0, $zero, $zero
.Lexit:
lw $ra, 28($sp)
lw $s2, 24($sp)
lw $s1, 20($sp)
lw $s0, 16($sp)
jr $ra
addiu $sp, $sp, 32
'''
DMA_C = '''
s32 f(s32 mode, s32 offset, M2C_UNK addr, s32 size) {
    s32 *reg;
    if (*(s32 *)0xA4600010 & 2) {
        do {} while (*(void *)0xA4600010 & 2);
    }
    dram = translate(addr);
    *(s32 *)0xA4600004 = (base | offset) & 0x1FFFFFFF;
    switch (mode) {
    case 0:
        reg = (s32 *)0xA460000C;
block_1:
        *reg = size - 1;
        return 0;
    case 1:
        reg = (s32 *)0xA4600008;
        goto block_1;
    default:
        return -1;
    }
}
'''


def test_dma_poll_preserves_both_length_registers_and_default_return():
    resolve = {'dram': 0xA4600000}.get
    candidate = kmc_cartridge_io.rewrite(DMA_C, 'f', DMA_ASM, resolve=resolve)
    assert '*(volatile u32 *)0xA4600000U = translate(addr);' in candidate
    assert 'return -1;' in candidate
    assert '(volatile u32 *)0xA4600008;' in candidate and '(volatile u32 *)0xA460000C;' in candidate
    assert '*_m2c_cart_length = size - 1;' in candidate
    assert not kmc_cartridge_io.rewrite(DMA_C.replace('size - 1', 'size'), 'f', DMA_ASM, resolve=resolve)
    assert not kmc_cartridge_io.rewrite(DMA_C, 'f', DMA_ASM, resolve={'dram': 0xA4600004}.get)

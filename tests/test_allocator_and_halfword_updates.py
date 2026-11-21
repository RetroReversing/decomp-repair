from decomprepair import aligned_allocator_request, ordered_halfword_updates

ALLOC_ASM = r'''
lw $v0, 16($sp)
mult $a3, $v0
mflo $a3
lw $v1, 8($a2)
lw $v0, 0($a2)
addiu $a0, $zero, -16
lw $a1, 4($a2)
addu $v0, $v0, $v1
addiu $a3, $a3, 15
and $a3, $a3, $a0
addu $a0, $a1, $a3
sltu $v0, $v0, $a0
bnez $v0, .Ldone
move $t0, $zero
move $t0, $a1
sw $a0, 4($a2)
.Ldone:
jr $ra
move $v0, $t0
'''
ALLOC = '''
u32 reserve(void *arg2, s32 arg3, s32 arg4) {
    u32 end;
    u32 start;
    u32 result;
    start = M2C_FIELD(arg2, u32 *, 4);
    end = start + (((arg3 * arg4) + 0xF) & ~0xF);
    result = 0;
    if ((u32) (M2C_FIELD(arg2, s32 *, 0) + M2C_FIELD(arg2, s32 *, 8)) >= end) {
        result = start;
        M2C_FIELD(arg2, u32 *, 4) = end;
    }
    return result;
}
'''


def test_restore_allocator_places_and_stage_size():
    candidate = aligned_allocator_request.rewrite(ALLOC, 'reserve', ALLOC_ASM)
    assert 's32 arg0, s32 arg1, void *arg2, s32 arg3, s32 arg4' in candidate
    assert candidate.index('__repair_alloc_size =') < candidate.index('start =')
    assert aligned_allocator_request.rewrite(ALLOC, 'reserve', ALLOC_ASM.replace('16($sp)', '20($sp)')) is None


def halfword_fixture():
    lines = [
        ('lw $v0, 4($a0)', 0x8C820004),
        ('lui $at, %hi(area + 0x10)', 0x3C018003), ('sh $v0, %lo(area + 0x10)($at)', 0xA4229100),
        ('lw $v0, 8($a0)', 0x8C820008),
        ('lui $at, %hi(area + 0x12)', 0x3C018003), ('sh $v0, %lo(area + 0x12)($at)', 0xA4229102),
        ('lw $v1, 12($a0)', 0x8C83000C), ('addiu $v0, $zero, 31', 0x2402001F),
        ('lui $at, %hi(area + 0x18)', 0x3C018003), ('sh $v0, %lo(area + 0x18)($at)', 0xA4229108),
        ('lui $at, %hi(area + 0x14)', 0x3C018003), ('sh $v1, %lo(area + 0x14)($at)', 0xA4239104),
        ('lw $v0, 16($a0)', 0x8C820010),
        ('lui $at, %hi(area + 0x1A)', 0x3C018003), ('sh $zero, %lo(area + 0x1A)($at)', 0xA420910A),
        ('lui $at, %hi(area + 0x1C)', 0x3C018003), ('sh $zero, %lo(area + 0x1C)($at)', 0xA420910C),
        ('lui $at, %hi(area + 0x16)', 0x3C018003), ('jr $ra', 0x03E00008),
        ('sh $v0, %lo(area + 0x16)($at)', 0xA4229106),
    ]
    asm = '\n'.join(f'/* {4*i:X} {0x80000000+4*i:08X} {word:08X} */ {line}'
                    for i, (line, word) in enumerate(lines))
    symbols = {'area': 0x800290F0, **{f'D_{a:08X}': a for a in range(0x80029100, 0x8002910D, 2)}}
    return asm, symbols.get


HALFWORDS = '''
void update(void *input) {
    M2C_FIELD(&area, s16 *, 0x10) = (s16) M2C_FIELD(input, s32 *, 4);
    M2C_FIELD(&area, s16 *, 0x12) = (s16) M2C_FIELD(input, s32 *, 8);
    M2C_FIELD(&area, s16 *, 0x14) = (s16) M2C_FIELD(input, s32 *, 12);
    M2C_FIELD(&area, s16 *, 0x18) = 31;
    M2C_FIELD(&area, s16 *, 0x1A) = 0;
    M2C_FIELD(&area, s16 *, 0x1C) = 0;
    M2C_FIELD(&area, s16 *, 0x16) = (s16) M2C_FIELD(input, s32 *, 16);
}
'''


def test_stage_halfword_updates_in_target_order_and_verify_each_address():
    asm, resolve = halfword_fixture()
    candidate = ordered_halfword_updates.rewrite(HALFWORDS, 'update', asm, resolve=resolve)
    assert candidate.index('D_80029108 = 0x1F;') < candidate.index('D_80029104 =')
    assert candidate.index('input + 0x10') < candidate.index('D_8002910A = 0;')
    assert ordered_halfword_updates.rewrite(HALFWORDS, 'update', asm.replace('A4229106', 'A4229116'),
                                            resolve=resolve) is None
    assert ordered_halfword_updates.rewrite(HALFWORDS.replace('= 31;', '= 32;'), 'update', asm,
                                            resolve=resolve) is None

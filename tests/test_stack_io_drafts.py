from decomprepair import measured_stack_drafts


def test_request_rebuilds_only_a_confirmed_eight_byte_copy():
    draft = '''
extern M2C_UNK device;
extern M2C_UNK config;
void send_byte(s8 input) {
    s8 sp0;
    s8 sp1;
    s8 sp2;
    s8 sp3;
    s8 sp4;
    s8 sp5;
    s8 sp6;
    s8 sp7;
    s32 index;
    s8 *dest;
    dest = &device + 12;
    index = 0;
    M2C_FIELD(&device, s32 *, 40) = 1;
    sp1 = 5;
    M2C_FIELD(&device, s8 *, 8) = input;
    sp0 = 7;
    sp2 = 2;
    sp3 = input;
    sp4 = 6;
    sp5 = 6;
    sp6 = 6;
    sp7 = 6;
    if ((s32) M2C_FIELD(&config, u8 *, 16) > 0) {
        do {
            M2C_FIELD(dest, s8 *, 0) = M2C_UNALIGNED32(sp0);
            M2C_FIELD(dest, M2C_UNK *, 4) = M2C_UNALIGNED32(sp4);
            index += 1;
            dest += 8;
        } while (index < (s32) M2C_FIELD(&config, u8 *, 16));
    }
    *dest = 12;
}
'''
    asm = '''
addiu $sp, $sp, -16
lbu $a1, %lo(config + 16)($a1)
addiu $a3, $a3, %lo(device + 12)
sw $v0, %lo(device + 40)($at)
sb $a0, %lo(device + 8)($at)
addiu $v0, $zero, 5
sb $v0, 1($sp)
addiu $v0, $zero, 7
sb $v0, 0($sp)
addiu $v0, $zero, 2
sb $v0, 2($sp)
sb $a0, 3($sp)
addiu $v0, $zero, 6
sb $v0, 4($sp)
sb $v0, 5($sp)
sb $v0, 6($sp)
sb $v0, 7($sp)
lwl $v0, 0($sp)
lwr $v0, 3($sp)
lwl $v1, 4($sp)
lwr $v1, 7($sp)
swl $v0, 0($a3)
swr $v0, 3($a3)
swl $v1, 4($a3)
swr $v1, 7($a3)
lbu $v0, %lo(config + 16)($v0)
addiu $a2, $a2, 1
slt $v0, $a2, $v0
addiu $a3, $a3, 8
addiu $v0, $zero, 12
sb $v0, 0($a3)
'''
    resolve = {'device': 0x80002000, 'config': 0x80003000}.get
    fixed = measured_stack_drafts.rewrite(draft, 'send_byte', asm, resolve=resolve)
    assert measured_stack_drafts.applies(asm)
    assert 'unsigned char bytes[8]' in fixed
    assert 'extern int D_80002028;' in fixed
    assert 'D_80002008 = input;' in fixed
    assert '__m2c_copy_packet.bytes[3] = input;' in fixed
    assert '__m2c_copy_index < D_80003010' in fixed
    assert 'M2C_' not in fixed
    assert not measured_stack_drafts.rewrite(draft, 'send_byte', asm)
    wrong_slot = asm.replace('sb $a0, 3($sp)', 'sb $v0, 3($sp)')
    assert not measured_stack_drafts.rewrite(draft, 'send_byte', wrong_slot, resolve=resolve)
    unexpected_use = draft.replace('*dest = 12;', '*dest = 12; log_write();')
    assert not measured_stack_drafts.rewrite(unexpected_use, 'send_byte', asm, resolve=resolve)


def test_inode_scan_requires_the_halfword_array_and_call_slot():
    draft = '''
s32 __osCheckId(void *);
s32 __osPfsRWInode(void *, u16 (*)[], M2C_UNK, s32);
s32 count_free(void *fs, s32 *out) {
    s32 sum;
    s32 error;
    s32 bank;
    s32 byte_bank;
    s32 first;
    s32 index;
    u16 *cursor;
    sum = 0;
    if (!(M2C_FIELD(fs, s32 *, 0) & 1)) { return 5; }
    error = 2;
    if (__osCheckId(fs) != 2) {
        bank = 0;
        if ((u8) M2C_FIELD(fs, u8 *, 0x64) > 0U) {
read_page:
            byte_bank = bank & 0xFF;
            error = __osPfsRWInode(fs, (u16 (*)[]) &sp10[0], 0, byte_bank);
            if (error == 0) {
                first = 1;
                if (byte_bank == 0) { first = M2C_FIELD(fs, s32 *, 0x60); }
                index = first;
                if (index < 0x80) {
                    cursor = &(&sp10[0])[index];
                    do { index += 1; sum += *cursor == 3; cursor += 2; }
                    while (index < 0x80);
                }
                bank += 1;
                if ((u32) (bank & 0xFF) >= (u8) M2C_FIELD(fs, u8 *, 0x64)) { goto done; }
                goto read_page;
            }
        } else {
done:
            *out = sum << 8;
            error = 0;
        }
    }
    return error;
}
'''
    asm = '''
addiu $sp, $sp, -0x130
sw $s0, 0x110($sp)
lw $v0, 0($s2)
jal __osCheckId
lbu $v0, 100($s2)
addiu $s4, $sp, 16
andi $s0, $s1, 255
addiu $a1, $sp, 16
addu $a2, $zero, $zero
jal __osPfsRWInode
lw $v0, 96($s2)
slti $v0, $a0, 128
lhu $v0, 0($v1)
xori $v0, $v0, 3
slti $v0, $a0, 128
addiu $v1, $v1, 2
sll $v0, $s3, 8
sw $v0, 0($s5)
'''
    assert measured_stack_drafts.applies(asm)
    fixed = measured_stack_drafts.rewrite(draft, 'count_free', asm)
    assert 'u16 __m2c_copy_words[128];' in fixed
    assert '__osPfsRWInode(void *, u16 *, M2C_UNK, s32);' in fixed
    assert '*out = __m2c_copy_free << 8;' in fixed
    assert not measured_stack_drafts.rewrite(draft, 'count_free', asm.replace('$a1, $sp, 16', '$a1, $sp, 20'))
    assert not measured_stack_drafts.rewrite(draft.replace('*cursor == 3', '*cursor == 4'), 'count_free', asm)

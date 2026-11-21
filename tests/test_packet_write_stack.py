from decomprepair import measured_stack_drafts

DRAFT = '''
M2C_UNK pif_lock();
M2C_UNK osRecvMesg(s32, M2C_UNK, M2C_UNK);
M2C_UNK __osSiRawStartDma(M2C_UNK, void *);
u32 pakQueryStatus(s32, u16 *);
M2C_UNK pfs_build_write_cmd(s32, M2C_UNK);
M2C_UNK pif_unlock();
extern M2C_UNK bus;
extern M2C_UNK command;
u32 write_packet(s32 queue, s32 channel, M2C_UNK data) {
    M2C_UNK sp10;
    M2C_UNK sp14;
    M2C_UNK sp18;
    u16 sp20;
    s32 kind;
    u32 error;
    void *io;
    void *dma;
    pif_lock();
    io = &bus + 16;
    error = pakQueryStatus(queue, &sp20);
    if (error == 0) {
        kind = sp20 & 0xC000 & 0xFFFF;
        if (kind == 0x8000) {
            if ((u32) (channel & 0xFF) >= 0x40U) { error = -1U; }
        } else if (kind != 0xC000) {
            error = 8;
        }
        if (error != 0) {
        } else {
wait:
            if (sp22 & 0x80) { pakQueryStatus(queue, &sp20); goto wait; }
            pfs_build_write_cmd(channel & 0xFF, data);
            dma = &bus + 16;
            __osSiRawStartDma(1, dma);
            osRecvMesg(queue, 0, 1);
            __osSiRawStartDma(0, dma);
            M2C_FIELD(&command, s8 *, 6) = 5;
            osRecvMesg(queue, 0, 1);
            sp10 = M2C_UNALIGNED32(M2C_FIELD(io, M2C_UNK *, 4));
            sp14 = M2C_UNALIGNED32(M2C_FIELD(io, M2C_UNK *, 8));
            sp18 = M2C_UNALIGNED32(M2C_FIELD(io, M2C_UNK *, 0xC));
            error = (u32) (sp11 & 0xC0) >> 4;
        }
    }
    pif_unlock();
    return error;
}
'''
ASM = '''
addiu $sp, $sp, -64
jal pif_lock
jal pakQueryStatus
addiu $a1, $sp, 32
lhu $v1, 32($sp)
addiu $s2, $s2, %lo(bus + (0x10 & 0xFFFF))
andi $v1, $v1, 49152
sltiu $v0, $v0, 64
jal pakQueryStatus
addiu $a1, $sp, 32
lbu $v0, 34($sp)
andi $v0, $v0, 128
jal pfs_build_write_cmd
addiu $s0, $s0, %lo(bus + 16)
jal __osSiRawStartDma
jal osRecvMesg
jal __osSiRawStartDma
sb $v0, %lo(command + 6)($at)
jal osRecvMesg
lwl $v0, 4($s2)
lwr $v0, 7($s2)
lwl $v1, 8($s2)
lwr $v1, 11($s2)
lwl $a0, 12($s2)
lwr $a0, 15($s2)
swl $v0, 16($sp)
swr $v0, 19($sp)
swl $v1, 20($sp)
swr $v1, 23($sp)
swl $a0, 24($sp)
swr $a0, 27($sp)
lbu $v0, 17($sp)
andi $v0, $v0, 192
srl $s0, $v0, 4
jal pif_unlock
'''


def test_packet_write_rebuilds_status_and_reply_in_stack_order():
    assert measured_stack_drafts.applies(ASM)
    fixed = measured_stack_drafts.rewrite(DRAFT, 'write_packet', ASM)
    assert '__m2c_copy_reply_t __m2c_copy_reply;\n    unsigned char __m2c_copy_status[4];' in fixed
    assert '__m2c_copy_status[2] & 0x80' in fixed
    assert '__m2c_copy_reply.bytes[1] & 0xc0' in fixed
    assert 'command[6] = 5;' in fixed


def test_packet_write_rejects_conflicting_declaration_and_wrong_status_slot():
    wrong_slot = ASM.replace('lbu $v0, 34($sp)', 'lbu $v0, 35($sp)')
    assert not measured_stack_drafts.applies(wrong_slot)
    assert not measured_stack_drafts.rewrite(DRAFT, 'write_packet', wrong_slot)
    assert not measured_stack_drafts.rewrite(DRAFT, 'write_packet', ASM, 'extern volatile char bus[];')
    assert not measured_stack_drafts.rewrite(DRAFT + '\nvoid foo(void) {}', 'write_packet', ASM)

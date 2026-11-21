"""The status reply overlaps an unsigned byte and halfword in the same stack buffer."""

from decomprepair.measured_stack_drafts import applies, rewrite

SOURCE = '''s32 read_status(s32 queue, M2C_UNK channel) {
    M2C_UNK sp10;
    M2C_UNK sp18;
    s32 result;
    s32 ret;

    __osPfsRequestOneChannel(channel);
    run_dma(1, &region);
    osRecvMesg(queue, &sp18, 1);
    result = run_dma(0, &region);
    osRecvMesg(queue, &sp18, 1);
    __osPfsGetOneChannelData(channel, &sp10);
    if (!(sp12 & 1) || (ret = 2, ((sp12 & 2) == 0))) {
        if (((u16) sp12 & 0x1FF) != 0x100) {
            return 1;
        }
        ret = 4;
        if (!(sp12 & 4)) {
            ret = result;
        }
        return ret;
    }
    return ret;
}'''
TARGET = '''jal __osPfsRequestOneChannel
nop
jal run_dma
nop
addiu $s0, $sp, 24
move $a1, $s0
jal osRecvMesg
nop
jal run_dma
nop
move $a1, $s0
jal osRecvMesg
nop
jal __osPfsGetOneChannelData
addiu $a1, $sp, 16
lbu $v1, 18($sp)
andi $v0, $v1, 1
beqz $v0, .Lword
andi $v0, $v1, 2
bnez $v0, .Lret
addiu $v0, $zero, 2
.Lword:
lhu $v0, 18($sp)
addiu $v1, $zero, 256
andi $v0, $v0, 511
beq $v0, $v1, .Lflag
nop
j .Lret
addiu $v0, $zero, 1
.Lflag:
lbu $v1, 18($sp)
andi $v1, $v1, 4
bnez $v1, .Lret
addiu $v0, $zero, 4
.Lret:
jr $ra
nop
'''


def test_status_buffer_addresses_match_both_read_widths():
    assert applies(TARGET)
    fixed = rewrite(SOURCE, 'read_status', TARGET)
    assert 's32 sp10[2];' in fixed and 's32 sp18[2];' in fixed
    assert '__osPfsGetOneChannelData(channel, sp10);' in fixed
    assert '*(u16 *)((u8 *)sp10 + 2) & 0x1FF' in fixed
    assert 'return result;' in fixed
    assert not rewrite(SOURCE, 'read_status', TARGET.replace('lhu $v0, 18', 'lbu $v0, 18'))
    assert not rewrite(SOURCE, 'read_status', TARGET.replace('$s0, $sp, 24', '$s0, $sp, 20'))

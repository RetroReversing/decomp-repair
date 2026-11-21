"""Check message-frame recovery through the same entry used for fresh drafts."""

from decomprepair import measured_stack_drafts as drafts

SOURCE = '''s32 fetch(s32 index) {
    M2C_UNK sp10;
    s16 sp28;
    M2C_UNK *sp2C;
    s32 sp30;
    M2C_UNK sp38;

    if (ready != 0) {
        osCreateMesgQueue(&sp10, &sp38, 1);
        sp30 = index;
        sp28 = 17;
        sp2C = &sp10;
        osSendMesg(&mailbox, &sp28, 1);
        osRecvMesg(&sp10, 0, 1);
        return sp34;
    }
    return 0;
}'''
TARGET = '''lui $v0, %hi(ready)
lw $v0, %lo(ready)($v0)
beqz $v0, .Lend
nop
addiu $a0, $sp, 16
addiu $a1, $sp, 56
jal osCreateMesgQueue
addiu $a2, $zero, 1
lui $a0, %hi(mailbox)
addiu $a0, $a0, %lo(mailbox)
addiu $a1, $sp, 40
addiu $a2, $zero, 1
addiu $v0, $zero, 17
sw $s0, 48($sp)
addiu $s0, $sp, 16
sh $v0, 40($sp)
jal osSendMesg
sw $s0, 44($sp)
move $a0, $s0
move $a1, $zero
jal osRecvMesg
addiu $a2, $zero, 1
lw $v0, 52($sp)
.Lend:
jr $ra
nop
'''


def test_recover_a_message_result_at_its_observed_offset():
    assert drafts.applies(TARGET)
    result = drafts.rewrite(SOURCE, 'fetch', TARGET)
    assert 'u8 __repair_message_queue[24];' in result
    assert '__repair_message_request.data = index;' in result
    assert 'if (ready == 0) return 0;' in result
    assert 'return __repair_message_request.result;' in result
    for target in (TARGET.replace('52($sp)', '56($sp)'), TARGET.replace('sw $s0, 44', 'sw $s0, 48'),
                   TARGET.replace('ready', 'other')):
        assert not drafts.rewrite(SOURCE, 'fetch', target)


def test_preserve_an_inline_frame_for_the_extended_message():
    source = '''s32 fetch(void) {
    s16 sp10;
    M2C_UNK *sp14;
    s32 sp18;
    s8 sp20;
    s16 sp22;
    M2C_UNK sp28;
    M2C_UNK sp40;

    if (ready == 0) { return -1; }
    osCreateMesgQueue(&sp28, &sp40, 1);
    sp10 = 17;
    sp20 = 0;
    sp18 = 0;
    sp22 = 0;
    sp14 = &sp28;
    osSendMesg(&mailbox, &sp10, 1);
    osRecvMesg(&sp28, 0, 1);
    return sp1C;
}'''
    target = (TARGET.replace('beqz', 'bnez').replace('$a0, $sp, 16', '$a0, $sp, 40')
              .replace('$a1, $sp, 56', '$a1, $sp, 64').replace('$a1, $sp, 40', '$a1, $sp, 16')
              .replace('sw $s0, 48($sp)', 'sw $zero, 24($sp)\nsb $zero, 32($sp)\nsh $zero, 34($sp)')
              .replace('$s0, $sp, 16', '$s0, $sp, 40').replace('sh $v0, 40', 'sh $v0, 16')
              .replace('sw $s0, 44', 'sw $s0, 20').replace('lw $v0, 52', 'lw $v0, 28'))
    result = drafts.rewrite(source, 'fetch', target)
    assert 'static inline s32 __repair_message_call(s16 __repair_message_kind)' in result
    assert 's32 fetch(void) { return __repair_message_call(17); }' in result
    assert not drafts.rewrite(source, 'fetch', target.replace('sb $zero, 32', 'sh $zero, 32'))


def test_recover_relocated_unaligned_packet_and_unsigned_terminator():
    source = '''extern M2C_UNK state;
void emit(s8 input) {
    s8 sp0;
    s8 sp1;
    s8 sp2;
    s8 sp3;
    s32 counter;
    s8 *dst;
    dst = &state + 28;
    counter = 3;
    M2C_FIELD(&state, s32 *, 72) = 1;
    sp0 = 7;
    sp1 = 9;
    sp2 = 11;
    sp3 = input;
    do { *dst = 0; counter -= 1; dst += 1; } while (counter >= 0);
    M2C_FIELD(dst, s8 *, 0) = M2C_UNALIGNED32(sp0);
    M2C_FIELD(dst, M2C_UNK *, 4) = M2C_UNALIGNED32(sp4);
    M2C_FIELD(dst, M2C_UNK *, 8) = M2C_UNALIGNED32(sp8);
    M2C_FIELD(dst, s8 *, 0xC) = 254;
}'''
    target = '''addiu $sp, $sp, -16
addiu $a2, $a2, %lo(state + 28)
sw $v0, %lo(state + 72)($at)
addiu $v0, $zero, 7
sb $v0, 0($sp)
addiu $v0, $zero, 9
sb $v0, 1($sp)
addiu $v0, $zero, 11
sb $v0, 2($sp)
sb $a0, 3($sp)
lwl $v0, 0($sp)
lwr $v0, 3($sp)
lwl $v1, 4($sp)
lwr $v1, 7($sp)
lwl $a0, 8($sp)
lwr $a0, 11($sp)
swl $v0, 0($a2)
swr $v0, 3($a2)
swl $v1, 4($a2)
swr $v1, 7($a2)
swl $a0, 8($a2)
swr $a0, 11($a2)
addiu $v0, $zero, 254
sb $v0, 12($a2)
'''
    assert drafts.applies(target)
    result = drafts.rewrite(source, 'emit', target)
    assert 'bytes[12]' in result
    assert 'M2C_FIELD(__m2c_copy_dst, u8 *, 0xC) = 254;' in result
    assert not drafts.rewrite(source, 'emit', target.replace('%lo(state + 72)', '%lo(state + 68)'))

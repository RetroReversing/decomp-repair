"""The reply extent, stack offsets and calls must agree with the draft."""

from decomprepair import draft_call_recovery, ido_switch_reply

SOURCE = '''
s32 dispatch(Request *arg) {
    Request *saved;
    s16 sp26;
    u8 sp24;
    M2C_UNK sp20;
    u32 sp1C;
    u32 next;
    u8 selector;
    saved = arg;
    selector = arg->kind;
    switch (selector) {
    case 0:
        stop(saved->task);
block_7:
        if (read_reply((s32) arg->kind, saved->task, &sp20) != 0) {
            return -6;
        }
        sp26 = 0;
        sp24 = saved->code;
        send_reply(&sp20, 0x20, 3);
        if (sp2C == 2) {
            sp24 = 7;
            send_reply(&sp20, 0x20, 4);
        }
        return 0;
    case 1:
        if (ready() != 0) {
            prepare();
            sp1C = get_pc(0x100);
            if (sp1C != 0) {
                next = sp1C - 4;
                sp1C = next;
                if (!(check(1, 8, next + 0x100) & 3)) {
                    resume();
                }
            }
        }
        goto block_7;
    default:
        return -8;
    }
}
'''

ASM = '''
addiu $sp, $sp, -0x48
addiu $a2, $sp, 0x20
lbu $a0, 7($t1)
jal read_reply
lw $a1, 4($t2)
beqz $v0, .Lok
nop
b .Lexit
addiu $v0, $zero, -6
lw $t3, 0x44($sp)
addiu $a0, $sp, 0x20
addiu $a1, $zero, 0x20
lbu $t4, 9($t3)
sh $zero, 0x26($sp)
addiu $a2, $zero, 3
jal send_reply
sb $t4, 0x24($sp)
lw $t5, 0x2C($sp)
addiu $at, $zero, 2
bne $t5, $at, .Lexit
nop
addiu $t6, $zero, 7
sb $t6, 0x24($sp)
addiu $a0, $sp, 0x20
addiu $a1, $zero, 0x20
jal send_reply
addiu $a2, $zero, 4
'''
ASM = '\n'.join(f'/* {i*4:04X} {0x80100000+i*4:08X} 00000000 */ {row}'
                for i, row in enumerate(ASM.strip().splitlines()))


def test_ido_reply_recovery_builds_addressed_fields_and_moves_switch_join():
    [(family, draft)] = draft_call_recovery.variants(SOURCE, 'dispatch', ASM, '', 'ido-7.1')
    assert family == 'ido_switch_reply'
    assert 'switch (arg->kind)' in draft
    assert 'goto' not in draft
    assert 'if (sp1C == 0) break;' in draft
    assert 'u8 _m2c_reply_pad_0[4]; u8 _m2c_reply_code;' in draft
    assert 's16 _m2c_reply_error;' in draft and 's32 _m2c_reply_flags;' in draft
    assert 'default:\n        return -8;\n    }\n    if (read_reply' in draft
    assert draft.count('(void *)&_m2c_reply_record') == 3
    assert draft.index('_m2c_reply_code = saved->code') < draft.index('_m2c_reply_error = 0')
    assert not draft_call_recovery.variants(SOURCE, 'dispatch', ASM, '', 'gcc-2.7.2-kmc')


def test_reply_requires_matching_extent_fields_and_unshadowed_storage():
    assert ido_switch_reply.applies(ASM)
    assert not ido_switch_reply.applies(ASM.replace('-0x48', '-0x38'))
    assert not ido_switch_reply.rewrite(SOURCE, 'dispatch', ASM.replace('lw $t5', 'lhu $t5'))
    assert not ido_switch_reply.rewrite(SOURCE.replace('0x20,', '0x1C,'), 'dispatch', ASM)
    assert not ido_switch_reply.rewrite(SOURCE, 'dispatch', ASM, 'extern int sp2C;')
    assert not ido_switch_reply.rewrite(SOURCE.replace('goto block_7;', 'return 0;'), 'dispatch', ASM)

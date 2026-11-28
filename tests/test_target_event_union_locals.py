from decomprepair.target_event_union_locals import variants

SOURCE = '''void f(void) {
    s32 unksp29;
    s32 unksp2A;
    s32 sp20;
    void *sp24;
    s32 sp28;
    u8 sp2C;
    {
        void *sp24_a1;
        s32 sp28_a1;
        sp20 = 0x16; sp24_a1 = voice; sp28_a1 = value;
        alEvtqPostEvent(queue, &sp20, delay);
    }
    {
        void *sp24_a2;
        u8 sp2C_a1;
        s32 sp28_a2;
        sp20 = 0x17; sp24_a2 = voice; sp2C_a1 = chan; sp28_a2 = value;
        alEvtqPostEvent(queue, &sp20, delay);
    }
    sp20 = 6; sp24 = voice; sp2C = chan; sp28 = value;
    alEvtqPostEvent(queue, &sp20, delay);
    {
        s32 sp28_a3;
        sp20 = 0x15; sp28_a3 = 0x80; unksp29 = key; unksp2A = 0;
        alEvtqPostEvent(queue, &sp20, delay);
    }
}
'''
ASM = '''
addiu $a1, $sp, 0x20
sh $v0, 0x20($sp)
sw $s1, 0x24($sp)
jal alEvtqPostEvent
sw $v1, 0x28($sp)
addiu $a1, $sp, 0x20
sh $v0, 0x20($sp)
sw $s1, 0x24($sp)
jal alEvtqPostEvent
sw $v1, 0x28($sp)
sb $v0, 0x2C($sp)
sb $v0, 0x28($sp)
sb $v0, 0x29($sp)
sb $zero, 0x2A($sp)
'''


def test_recovers_word_and_byte_views_of_target_event():
    children = variants(SOURCE, 'f', ASM)
    assert len(children) == 1
    text = children[0][1]
    assert 'union { s32 value; u8 bytes[4]; }' in text
    assert '__repair_event.ptr = voice;' in text
    assert '__repair_event.data.bytes[1] = key;' in text
    assert text.count('&__repair_event.type') == 4


def test_requires_target_witness_and_no_independent_alias_reads():
    assert not variants(SOURCE, 'f', ASM.replace('sb $zero, 0x2A($sp)', 'nop'))
    assert not variants(SOURCE.replace('sp20 = 6;', 'use(sp24); sp20 = 6;'), 'f', ASM)
    assert not variants(SOURCE.replace('sp20 = 6;', 'use(sp20); sp20 = 6;'), 'f', ASM)
    assert not variants(SOURCE, 'f', ASM, '#define chan collision')

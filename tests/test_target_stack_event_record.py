from decomprepair import target_stack_event_record as repair

ASM = '''addiu $a1, $sp, 0x20
sh $v0, 0x20($sp)
sw $s1, 0x24($sp)
sw $v1, 0x28($sp)
sb $s5, 0x2c($sp)
jal post
nop
addiu $a1, $sp, 0x20
jal post
nop
'''
SOURCE = '''void f(void *queue, void *voice, int value) {
    s32 sp20;
    void *sp24;
    s32 sp28;
    u8 sp2C;
    if (value) {
        sp20 = 0x16;
        sp24 = voice;
        sp28 = value;
        post(queue, &sp20, value);
    } else {
        sp20 = 0x17;
        sp24 = voice;
        sp2C = 2;
        sp28 = value;
        post(queue, &sp20, value);
    }
    sp20 = value + 1;
    use(sp20);
}
'''


def test_recovers_record_and_keeps_other_local_use():
    assert repair.target_bases(ASM) == [0x20]
    out = repair.variants(SOURCE, 'f', ASM)
    assert len(out) == 1
    text = out[0][1]
    assert 'struct { s16 type; s16 pad; void *ptr; s32 value; u8 chan; u8 tail[3]; } repair_stack_event;' in text
    assert 'repair_stack_event.type = 0x16;' in text
    assert 'repair_stack_event.chan = 2;' in text
    assert 'post(queue, &repair_stack_event.type, value);' in text
    assert 'sp20 = value + 1;' in text


def test_requires_repeated_target_address_and_all_field_stores():
    assert not repair.variants(SOURCE, 'f', ASM.replace('sb $s5, 0x2c($sp)', 'nop'))
    assert not repair.variants(SOURCE, 'f', ASM.replace('addiu $a1, $sp, 0x20', 'nop', 1))
    assert not repair.variants(SOURCE.replace('    sp20 = value + 1;', '    use(sp24);\n    sp20 = value + 1;'), 'f', ASM)
    assert not repair.variants(SOURCE, 'f', ASM, 'typedef volatile int s32;')


def test_rejects_shadows_and_member_name_collisions():
    assert not repair.variants(SOURCE.replace('    if (value)', '    { int sp24; use(sp24); }\n    if (value)'), 'f', ASM)
    assert not repair.variants(SOURCE.replace('sp24 = voice;', 'sp24 = obj->sp24;', 1), 'f', ASM)

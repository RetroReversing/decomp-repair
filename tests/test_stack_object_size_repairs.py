"""Stack objects sized by the target's frame."""
from decomprepair import stack_object_size_repairs as s

SOURCE = '''void f(s32 arg0, s32 arg1) {
    M2C_UNK sp10;
    M2C_UNK sp50;
/* Inferred frame reservation; original purpose unknown. */
char __repair_stack_padding[16];

    g(&sp10, arg0);
    g(&sp50, arg1);
    h(&sp10, &sp50);
}
'''
ASM = '''addiu      $sp, $sp, -0xA0
sw         $ra, 0x94($sp)
sw         $s0, 0x90($sp)
'''


def test_each_object_runs_to_the_next_or_the_saved_registers():
    (family, stripped), (_, kept) = s.variants(SOURCE, 'f', ASM)
    assert family == 'stack_object_size'
    assert 'u8 sp10[0x40];' in stripped and 'u8 sp50[0x40];' in stripped
    assert 'g(sp10, arg0);' in stripped and 'h(sp10, sp50);' in stripped
    assert '__repair_stack_padding' not in stripped and '__repair_stack_padding' in kept


def test_left_alone_when_used_by_value_or_word_sized():
    by_value = SOURCE.replace('h(&sp10, &sp50);', 'h(sp10, &sp50);')
    small = ASM.replace('0x94', '0x58').replace('0x90', '0x54')  # sp50 is a word: 0x50..0x54
    assert s.variants(by_value, 'f', small) == []
    assert s.variants(SOURCE, 'f', '') == []


def test_stack_record_extent_keeps_scalar_reads_and_escaped_addresses():
    from decomprepair.stack_object_size_repairs import record_variants

    source = '''
void f(void) {
    s16 sp10;
    read(&sp10);
    if (sp10 == 3) {
        sp10 = 4;
    }
    send(&sp10);
}
'''
    asm = '''
addiu $sp, $sp, -40
sw $ra, 36($sp)
sw $s0, 32($sp)
jal read
addiu $a0, $sp, 16
lhu $v0, 16($sp)
sh $v1, 16($sp)
jal send
addiu $a0, $sp, 16
'''
    [(family, fixed)] = record_variants(source, 'f', asm)
    assert family == 'stack_record_extent'
    assert 'struct { s16 __repair_record_prefix; u8 __repair_record_bytes[14]; } sp10;' in fixed
    assert 'if (sp10.__repair_record_prefix == 3)' in fixed
    assert 'send(&sp10.__repair_record_prefix);' in fixed
    assert not record_variants(source, 'f', asm.replace('16($sp)', '18($sp)'))
    assert not record_variants(source, 'f', asm, '#define sp10 other')
    assert not record_variants(source.replace('sp10 = 4;', 's16 sp10 = 4;'), 'f', asm)

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

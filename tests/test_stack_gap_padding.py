"""The frame the target reserves below its lowest stack object, declared as an unused array."""
from decomprepair import registry
from decomprepair import stack_gap_padding as s

SOURCE = '''s32 f(s32 arg0, M2C_UNK arg1) {
    s32 sp60;
    s32 temp_s0;
    void *temp_v0_2;

    g();
    temp_s0 = h(arg0);
    sp60 = temp_s0;
    k(arg1, &sp60, temp_s0);
    return temp_s0;
}
'''
ASM = '''addiu      $sp, $sp, -0x80
sw         $s0, 0x68($sp)
sw         $s4, 0x78($sp)
sw         $ra, 0x7C($sp)
jal        g
sw         $s1, 0x6c($sp)
jal        h
sw         $s2, 0x60($sp)
addiu      $a1, $sp, 0x60
jal        k
lw         $ra, 0x7C($sp)
addiu      $sp, $sp, 0x80
'''


def test_the_gap_under_the_lowest_object_is_declared_after_the_other_locals():
    # 0x60 - 16 bytes of outgoing arguments = 0x50: a blues-brothers-style `s32 pad[20];` (16 -> 0 on a KMC function)
    first, second = s.variants(SOURCE, 'f', ASM)
    assert first[0] == s.FAMILY
    assert first[1].index('void *temp_v0_2;\n    s32 pad[20];') > 0
    assert second[1].index('{\n    s32 pad[20];\n    s32 sp60;') > 0


def test_a_byte_array_when_the_gap_is_not_a_doubleword_multiple():
    asm = ASM.replace('0x60', '0x5C').replace('0x68', '0x64')
    assert 'u8 pad[76];' in s.variants(SOURCE.replace('sp60', 'sp5C'), 'f', asm)[0][1]


def test_arguments_stored_below_the_object_are_not_padding():
    asm = ASM.replace('jal        g\n', 'sw         $a0, 0x10($sp)\nsw         $a1, 0x14($sp)\njal        g\n')
    assert 's32 pad[18];' in s.variants(SOURCE, 'f', asm)[0][1]


def test_nothing_without_evidence():
    assert not s.variants(SOURCE, 'f', ASM.replace('0x60($sp)', '0x58($sp)').replace('$sp, 0x60', '$sp, 0x58'))  # name is not the target's
    assert not s.variants(SOURCE.replace('sp60', 'sp10'), 'f', ASM.replace('0x60', '0x10'))  # nothing under it
    assert not s.variants(SOURCE.replace('s32 sp60;', 's32 sp60;\n    s32 pad[4];'), 'f', ASM)  # already padded
    assert not s.variants(SOURCE, 'f', '')


def test_a_small_gap_is_left_to_the_measured_families():
    assert not s.variants(SOURCE.replace('sp60', 'sp18'), 'f', ASM.replace('0x60', '0x18'))


def test_it_is_declared():
    assert 'stack_gap_padding' in [r.module for r in registry.declared()]


def test_a_function_with_no_stack_object_is_padded_up_to_its_lowest_saved_register():
    # a frame of 0x98 whose only slots are the two saves at 0x90 and 0x94: 0x80 bytes the original never read
    source = 'void f(void) {\n    s32 *base;\n\n    g();\n}\n'
    asm = 'addiu $sp, $sp, -0x98\nsw $ra, 0x94($sp)\njal g\nsw $s0, 0x90($sp)\nlw $ra, 0x94($sp)\nlw $s0, 0x90($sp)\naddiu $sp, $sp, 0x98\n'
    first, second = s.variants(source, 'f', asm)
    assert 's32 *base;\n    s32 pad[32];' in first[1] and '{\n    s32 pad[32];\n    s32 *base;' in second[1]
    assert not s.variants(source, 'f', asm.replace('jal g', 'sw $a0, 0x20($sp)\njal g'))  # an object nobody named

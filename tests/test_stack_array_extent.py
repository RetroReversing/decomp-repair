"""A stack array handed to a call, grown to the room the target's frame gives it."""
from decomprepair import registry
from decomprepair import stack_array_extent as x

SOURCE = '''void f(void *arg0) {
    s16 sp10[3];
    s32 sp18[2];
    s32 sp28;

    sp10[0] = 1;
    sp10[1] = 2;
    sp10[2] = 0;
    transform(sp10, sp18, &sp28);
    M2C_FIELD(arg0, s16 *, 0x78) = (s16) (sp18[0] >> 7);
    M2C_FIELD(arg0, s16 *, 0x7A) = (s16) (sp18[1] >> 6);
}
'''
ASM = '''addiu $sp, $sp, -0x38
sw $ra, 0x34($sp)
sw $s0, 0x30($sp)
sh $v0, 0x10($sp)
sh $v0, 0x12($sp)
sh $zero, 0x14($sp)
addiu $a0, $sp, 0x10
addiu $a1, $sp, 0x18
jal transform
addiu $a2, $sp, 0x28
'''


def test_the_vector_grows_to_the_next_object():
    # An N64 function (KMC GCC 2.7.2 -O1 -g): frame 0x30 against 0x38 until the callee's output vector had 3 words.
    out = [text for family, text in x.variants(SOURCE, 'f', ASM)]
    assert all(family == 'stack_array_extent' for family, _ in x.variants(SOURCE, 'f', ASM))
    assert any('s32 sp18[3];' in text and 's16 sp10[3];' in text for text in out)
    assert any('s32 sp18[4];' in text for text in out)
    assert any('s16 sp10[4];' in text for text in out)
    assert not any('sp18[5]' in text for text in out)


def test_left_alone_otherwise():
    assert x.variants(SOURCE.replace('transform(sp10, sp18, &sp28);', 'transform(&sp28);'), 'f', ASM) == []
    assert x.variants(SOURCE, 'f', '') == []
    # no room past what is declared
    tight = ASM.replace('0x28($sp)', '0x20($sp)').replace('addiu $a2, $sp, 0x28', 'addiu $a2, $sp, 0x20')
    assert not any('sp18[3]' in text for _, text in x.variants(SOURCE, 'f', tight))


def test_declared():
    repair = registry.get('stack_array_extent')
    assert repair and repair.families == ('stack_array_extent',) and 'asm' in repair.needs

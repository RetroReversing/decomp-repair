"""A stack object m2c declared as one scalar, sized as the target's frame lays it out."""
from decomprepair import stack_extent_repairs as x

SOURCE = '''void f(s32 arg0) {
    s32 sp30;

    sprintf(&sp30, D_8011F010, arg0);
    g(&sp30);
}
'''
ASM = '''addiu      $sp, $sp, -0x58
sw         $ra, 0x54($sp)
sw         $s0, 0x50($sp)
addiu      $a0, $sp, 0x30
'''


def test_the_buffer_reaches_the_next_slot():
    # An N64 function: frame 0x58 against the draft's 0x40; with the buffer to $s0's slot the frame was right.
    (family, out), (_, typed) = x.variants(SOURCE, 'f', ASM)
    assert family == 'stack_object_extent'
    assert 'char sp30[0x20];' in out and 'sprintf(sp30,' in out and 'g(sp30);' in out and '&sp30' not in out
    assert 's32 sp30[8];' in typed


def test_left_alone_otherwise():
    assert x.variants(SOURCE.replace('    g(&sp30);', '    g(sp30);'), 'f', ASM) == []  # read as a value too
    assert x.variants(SOURCE, 'f', ASM.replace('0x50($sp)', '0x34($sp)').replace('0x54($sp)', '0x38($sp)')) == []
    assert x.variants(SOURCE, 'f', '') == []

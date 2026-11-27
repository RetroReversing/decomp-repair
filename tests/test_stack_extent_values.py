"""A stack byte that is both passed by address and read: a buffer, with its reads naming the first element."""
from decomprepair import stack_extent_repairs as extent

ASM = '''addiu $sp, $sp, -0x60
sw $ra, 0x5c($sp)
addiu $a0, $sp, 0x20
addiu $a1, $sp, 0x40
'''
SOURCE = '''void f(u8 *arg0) {
    u8 sp20;
    s32 sp40;

    copy(&sp20, arg0);
    if (sp20 != 0) {
        find(&sp20, &sp40);
    }
}
'''


def test_the_scalar_becomes_a_buffer_filling_the_room_below_the_next_slot():
    (family, text), = [child for child in extent.variants(SOURCE, 'f', ASM) if 'sp20[' in child[1]]
    assert family == extent.FAMILY
    assert 'u8 sp20[32];' in text
    assert 'copy(sp20, arg0);' in text and 'if (sp20[0] != 0) {' in text and 'find(sp20, &sp40);' in text


def test_a_scalar_never_passed_by_address_is_left_alone():
    plain = SOURCE.replace('copy(&sp20, arg0);', 'sp20 = *arg0;').replace('find(&sp20, &sp40);', 'g(sp20);')
    assert all('sp20[' not in text for _, text in extent.variants(plain, 'f', ASM))

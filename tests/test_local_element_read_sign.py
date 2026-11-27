from decomprepair import local_element_read_sign

SOURCE = '''s32 rank(void)
{
    s8 slot[2];
    slot[0] = -1;
    slot[1] = -1;
    fill(slot);
    slot[0]++;
    return ((slot[1] + 1) << 4) | (slot[0] + 1);
}
'''


def test_each_read_cast_to_the_targets_load_then_all():
    children = [child for _, child in local_element_read_sign.variants(SOURCE, 'rank', 'lbu $v0, 0x11($sp)\n')]
    line = '    return ((slot[1] + 1) << 4) | (slot[0] + 1);'
    assert children == [SOURCE.replace(line, line.replace('slot[1]', '(u8) slot[1]')),
                        SOURCE.replace(line, line.replace('slot[0]', '(u8) slot[0]')),
                        SOURCE.replace(line, '    return (((u8) slot[1] + 1) << 4) | ((u8) slot[0] + 1);')]


def test_nothing_without_a_stack_load_of_the_other_sign():
    for asm in ('lb $v0, 0x11($sp)\n', 'lbu $v0, 0x11($a0)\n', 'lhu $v0, 0x10($sp)\n', ''):
        assert local_element_read_sign.variants(SOURCE, 'rank', asm) == []

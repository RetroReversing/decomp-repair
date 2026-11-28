"""Two address-taken stack slots with a frame pad between them, declared as one byte buffer."""
from decomprepair import stack_slots_one_buffer as r

SOURCE = '''s32 f(s32 arg0, M2C_UNK arg1) {
    M2C_UNK sp18;
    char frame_pad[504];
    M2C_UNK sp5C;

    if (g(arg1, 0, &sp18) & 0xFF) {
        h(arg0, &sp5C);
        return 1;
    }
    return 0;
}
'''


def test_two_slots_and_the_pad_become_one_buffer():
    ((family, out),) = r.variants(SOURCE, 'f')
    assert family == 'stack_slots_one_buffer'
    assert '    u8 sp18_buf[512];\n' in out
    assert 'frame_pad' not in out and 'M2C_UNK sp' not in out
    assert 'g(arg1, 0, (M2C_UNK *) sp18_buf)' in out
    assert 'h(arg0, (M2C_UNK *) (sp18_buf + 0x44))' in out


def test_nothing_without_a_pad_or_when_a_slot_is_read():
    assert not r.variants(SOURCE.replace('    char frame_pad[504];\n', ''), 'f')
    assert not r.variants(SOURCE.replace('return 0;', 'return sp18;'), 'f')

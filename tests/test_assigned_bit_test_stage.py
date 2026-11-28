from decomprepair import assigned_bit_test_stage as repair

SOURCE = '''void poll(void) {
    s32 a;
    s32 b;
    s32 c;
    a = (*pads[0] & 0x200) != 0;
    b = (u32) (*pads[0] & 4) > 0U;
    flags[2] = (s8) ((buttons & 0x800) != 0);
    c = (*pads[0] & 1) != 0;
    if (a) b = (*pads[0] & 8) != 0;
}
'''


def test_stages_every_single_bit_test_together_and_alone():
    out = [text for _, text in repair.variants(SOURCE, 'poll')]
    every = out[0]
    assert 'int bitTest0;' in every and 'int bitTest2;' in every
    assert 'bitTest0 = *pads[0] & 0x200;\n    a = bitTest0 != 0;' in every
    assert 'bitTest1 = *pads[0] & 4;\n    b = bitTest1 != 0;' in every
    assert 'bitTest2 = buttons & 0x800;\n    flags[2] = (s8) (bitTest2 != 0);' in every
    assert 'c = (*pads[0] & 1) != 0;' in every  # bit 0 needs no staging
    assert 'if (a) b = (*pads[0] & 8) != 0;' in every  # an unbraced body is not split in two
    assert out[1].count('bitTest = ') == 3
    assert any(text.count('bitTest0 != 0') == 1 and 'bitTest1' not in text for text in out[2:])


def test_leaves_calls_masks_of_several_bits_and_assignments():
    source = 'void f(void) {\n    a = (read() & 4) != 0;\n    a = (x & 6) != 0;\n    a = (p[i++] & 4) != 0;\n}\n'
    assert repair.variants(source, 'f') == []

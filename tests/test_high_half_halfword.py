from decomprepair import high_half_halfword as r

SWAP = '''u32 swap(u32 *in) {
    u32 temp_s0;
    u32 temp_v1;
    u32 out;

    temp_s0 = in[1];
    temp_v1 = temp_s0 >> 0x10;
    out = ((((temp_s0 & 0xFF) << 8) + ((u32) (temp_s0 & 0xFF00) >> 8)) << 0x10) + (((temp_v1 & 0xFF) << 8) + (temp_v1 >> 8));
    return out;
}
'''


def test_high_half_of_an_unsigned_word_is_declared_halfword():
    found = r.variants(SWAP, 'swap')
    assert [family for family, _ in found] == [r.FAMILY]
    text = found[0][1]
    assert 'u16 temp_v1;' in text and 'u32 temp_s0;' in text


def test_a_sign_sensitive_reader_keeps_the_wide_local():
    compared = SWAP.replace('return out;', 'out = temp_v1 - 1 > 5;\n    return out;')
    assert r.variants(compared, 'swap') == []
    shifted = SWAP.replace('(temp_v1 >> 8)', '((temp_v1 - 1) >> 8)')
    assert r.variants(shifted, 'swap') == []


def test_a_signed_source_or_a_second_assignment_is_left_alone():
    assert r.variants(SWAP.replace('u32 temp_s0;', 's32 temp_s0;'), 'swap') == []
    twice = SWAP.replace('return out;', 'temp_v1 += 1;\n    return out;')
    assert r.variants(twice, 'swap') == []

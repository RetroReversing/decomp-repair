from decomprepair import signed_postdec_counter as r

DECODER = '''void f(u8 *out, u32 *in) {
    u32 n;
    u32 a;
    n = in[0] & 0x7FFF;
    if (n-- != 0) {
        do {
            a = *in++;
            *out++ = a;
        } while (n-- != 0);
    }
}
'''


def test_unsigned_postdecrement_counter_is_retyped_signed():
    found = r.variants(DECODER, 'f')
    assert [family for family, _ in found] == [r.FAMILY]
    text = found[0][1]
    assert 's32 n;' in text and 'u32 a;' in text and 'u32 n;' not in text


def test_unsigned_word_and_unsigned_int_keep_the_matching_signed_spelling():
    plain = DECODER.replace('u32 n;', 'unsigned n;')
    assert 'int n;' in r.variants(plain, 'f')[0][1]
    spelled = DECODER.replace('u32 n;', 'unsigned int n;')
    assert 'int n;' in r.variants(spelled, 'f')[0][1] and 'unsigned' not in r.variants(spelled, 'f')[0][1]


def test_counter_that_is_ordered_or_has_its_address_taken_is_left_alone():
    ordered = DECODER.replace('} while (n-- != 0);', '} while (n-- != 0 && n < 100);')
    assert r.variants(ordered, 'f') == []
    taken = DECODER.replace('a = *in++;', 'a = *in++; g(&n);')
    assert r.variants(taken, 'f') == []


def test_a_counter_never_tested_by_postdecrement_is_left_alone():
    plain = DECODER.replace('n-- != 0', 'n != 0')
    assert r.variants(plain, 'f') == []


def test_only_the_counter_is_retyped_when_two_locals_are_unsigned():
    two = DECODER.replace('u32 a;', 'u32 a;\n    u32 m;').replace('a = *in++;', 'a = *in++; m = a;')
    found = r.variants(two, 'f')
    assert len(found) == 1 and 's32 n;' in found[0][1] and 'u32 m;' in found[0][1]

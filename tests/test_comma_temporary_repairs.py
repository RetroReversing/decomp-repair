"""m2c's comma temporary in a condition, written where it's used."""
from decomprepair import comma_temporary_repairs as c

SOURCE = '''void *f(s32 arg0) {
    s32 temp_v1;
    u32 temp_a0;

    temp_a0 = arg0 & 0xFFFF;
    if ((temp_a0 >= 0x10U) || (temp_v1 = temp_a0 * 0x18, (*(&D_80107B68 + temp_v1) == 0))) {
        return g(0x3004);
    }
    return temp_v1 + &D_80107B6A;
}
'''


def test_the_temporary_goes_and_its_value_is_used():
    # An N64 function at 75%: 90.9% so, exact with two existing families after it.
    (family, out), = c.variants(SOURCE, 'f')
    assert family == 'comma_temporary_inline'
    assert 'temp_v1' not in out
    assert '|| ((*(&D_80107B68 + (temp_a0 * 0x18)) == 0))) {' in out
    assert 'return (temp_a0 * 0x18) + &D_80107B6A;' in out


def test_left_alone_otherwise():
    assert c.variants(SOURCE.replace('temp_v1 = temp_a0 * 0x18,', 'temp_v1 = h(temp_a0),'), 'f') == []  # a call
    changed = SOURCE.replace('    return temp_v1 +', '    temp_a0 = 1;\n    return temp_v1 +')
    assert c.variants(changed, 'f') == []  # its input changes before a use
    again = SOURCE.replace('    return temp_v1 +', '    temp_v1 = 2;\n    return temp_v1 +')
    assert c.variants(again, 'f') == []  # assigned again

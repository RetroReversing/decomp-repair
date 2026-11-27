from decomprepair.narrow_parameter_wide_copy import FAMILY, variants

SOURCE = '''void f(s16 arg0) {
    s32 temp;

    if ((g(3) < 0x18) && ((u32) ((u16) arg0) < 0xCU)) {
        temp = (s32) (arg0 << 0x10) >> 0xE;
        h(D + temp, arg0 * 6);
    }
}
'''


def children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_word_parameter_narrow_local_and_cast_reads_on_the_word():
    """The exact child on an N64 function (SN GCC 2.7.2 -O1, 64 instructions): 5 -> 0."""
    first = children()[0]
    assert 'void f(s32 arg0_in) {\n    s16 arg0 = arg0_in;' in first
    assert '((u16) arg0_in) < 0xCU' in first
    assert '(arg0 << 0x10)' in first and 'arg0 * 6' in first


def test_every_read_through_the_local_is_the_second_child():
    second = children()[1]
    assert '((u16) arg0) < 0xCU' in second
    assert 'arg0_in' not in second.split('{', 1)[1].split(';', 1)[1]


def test_unsigned_and_byte_parameters():
    out = children(SOURCE.replace('s16 arg0', 'u8 arg0').replace('(u16) arg0', '(u8) arg0'))
    assert 'void f(u32 arg0_in) {\n    u8 arg0 = arg0_in;' in out[0]
    assert '(u8) arg0_in' in out[0]


def test_a_wider_cast_reads_the_local():
    out = children(SOURCE.replace('(u16) arg0', '(u32) arg0'))
    assert len(out) == 1 and '(u32) arg0)' in out[0]


def test_left_alone():
    assert children(SOURCE.replace('s16 arg0', 's32 arg0')) == []
    assert children(SOURCE.replace('        h(', '        arg0 = 1;\n        h(')) == []
    assert children(SOURCE.replace('h(D + temp, arg0 * 6)', 'h(&arg0)')) == []

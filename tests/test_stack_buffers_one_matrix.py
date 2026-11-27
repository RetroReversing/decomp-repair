"""Equal stack buffers at consecutive offsets become one two-dimensional array."""
from decomprepair import stack_buffers_one_matrix as m

SOURCE = '''typedef int s32;
typedef unsigned char u8;
s32 h(s32, s32 *);

void f(s32 arg0) {
    s32 sp18;
    s32 sp10[4];
    char sp20[0x10];
    u8 sp30[0x10];
    u8 sp40[0x10];
    s32 best;

    h(arg0 + 0x18, sp10);
    h(arg0 + 0x20, sp20);
    h(arg0 + 0x28, sp30);
    h(arg0 + 0x30, sp40);
    best = sp18;
    best += sp10[1];
}
'''


def test_four_equal_buffers_become_rows_and_the_word_inside_the_first_an_element():
    ((family, text),) = m.variants(SOURCE, 'f')
    assert family == m.FAMILY
    assert 's32 sp10_rows[4][4];' in text
    for row in range(4):
        assert f'h(arg0, sp10_rows[{row}]);'.replace('arg0,', f'arg0 + 0x{0x18 + 8 * row:X},') in text
    assert 'best = sp10_rows[0][2];' in text
    assert 'sp10_rows[0][1]' in text
    assert 'sp20' not in text and 'sp18' not in text and 'char sp' not in text


def test_a_single_buffer_unequal_sizes_or_indexed_bytes_are_left_alone():
    assert m.variants(SOURCE.replace('    char sp20[0x10];\n    u8 sp30[0x10];\n', ''), 'f') == []
    assert m.variants(SOURCE.replace('sp40[0x10]', 'sp40[8]'), 'f') != []  # the first three still form a run
    wide = SOURCE.replace('u8 sp30[0x10]', 'u8 sp30[0x20]').replace('u8 sp40[0x10]', 'u8 sp40[0x20]')
    ((_, text),) = m.variants(wide, 'f')
    assert 's32 sp10_rows[2][4];' in text and 'u8 sp30[0x20];' in text
    assert m.variants(SOURCE.replace('best = sp18;', 'best = sp20[1];'), 'f') == []


def test_the_byte_walk_over_the_rows_is_also_offered_as_a_row_subscript():
    source = SOURCE.replace('    best += sp10[1];\n', '    best += *(s32 *)((s8 *)sp10 + i * 0x10 + 8);\n').replace('s32 best;', 's32 best;\n    s32 i;')
    plain, rowed = [text for _, text in m.variants(source, 'f')]
    assert '(s8 *)sp10_rows[0] + i * 0x10 + 8' in plain
    assert 'best += sp10_rows[i][2];' in rowed

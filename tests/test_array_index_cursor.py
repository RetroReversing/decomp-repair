from decomprepair import array_index_cursor as r

SOURCE = '''extern u8 D_TABLE[];

void f(u32 bits) {
    u32 i;
    i = 0;
    do {
        D_TABLE[i] = 0;
        i++;
    } while ((i >> bits) == 0);
}
'''


def test_indexed_fill_becomes_a_cursor_started_at_the_table():
    found = r.variants(SOURCE, 'f')
    assert [family for family, _ in found] == [r.FAMILY]
    text = found[0][1]
    assert '{ u8 *cursor = D_TABLE; do {' in text and '*cursor++ = 0;' in text and 'D_TABLE[i]' not in text
    assert 'i++;' in text and '} while ((i >> bits) == 0); }' in text


def test_a_counter_not_known_to_be_zero_starts_the_cursor_at_its_element():
    text = r.variants(SOURCE.replace('    i = 0;\n', '    i = g();\n'), 'f')[0][1]
    assert 'u8 *cursor = D_TABLE + i;' in text


def test_a_table_read_in_the_loop_or_a_counter_in_the_value_is_left_alone():
    assert not r.variants(SOURCE.replace('D_TABLE[i] = 0;', 'D_TABLE[i] = D_TABLE[0];'), 'f')
    assert not r.variants(SOURCE.replace('D_TABLE[i] = 0;', 'D_TABLE[i] = i;'), 'f')


def test_an_undeclared_table_is_left_alone():
    assert not r.variants(SOURCE.replace('extern u8 D_TABLE[];\n', ''), 'f')

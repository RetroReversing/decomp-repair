from decomprepair import loop_table_local as lt

SOURCE = """\
extern u8 *Lines[];
extern u8 End[];
s32 same(u8 *, u8 *);
void draw(void)
{
    s32 i;
    i = 0;
    while (same(End, Lines[i]) != 0) {
        if (i == 0) {
            title(Lines[0]);
        } else {
            line(Lines[i]);
        }
        i++;
    }
}
"""


def test_the_table_is_named_before_the_loop_and_used_for_every_access():
    [(family, text)] = lt.variants(SOURCE, 'draw')
    assert family == 'loop_table_local'
    assert '    __typeof__(Lines[0]) *table;' in text
    assert 'i = 0;\n    table = Lines;\n    while (same(End, table[i]) != 0) {' in text
    assert 'title(table[0]);' in text and 'line(table[i]);' in text


def test_an_array_passed_whole_or_indexed_only_by_literals_is_left():
    assert lt.variants(SOURCE.replace('i++;', 'sort(Lines);\n        i++;'), 'draw') == []
    literal = SOURCE.replace('Lines[i]', 'Lines[1]')
    assert lt.variants(literal, 'draw') == []


def test_a_header_declaration_counts():
    header = 'extern u8 *Lines[];\n'
    [(_, text)] = lt.variants(SOURCE.replace(header, ''), 'draw', header)
    assert 'table = Lines;' in text


def test_a_single_read_in_the_loop_with_another_before_it_gets_a_local_too():
    source = '''extern int Sizes[];
void f(int n)
{
    int i;
    g(Sizes[n]);
    for (i = 0; i < n; i++) {
        h(Sizes[i]);
    }
}
'''
    [(_, text)] = lt.variants(source, 'f')
    assert 'table = Sizes;\n    for' in text
    assert 'g(Sizes[n]);' in text and 'h(table[i]);' in text

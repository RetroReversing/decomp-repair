from decomprepair import nested_row_pointer_local

SOURCE = '''extern u8 *TABLE[];
extern u16 G;
void f(Obj *o) {
    Row *row;
    row = &o->rows[TABLE[G][o->kind * 2]];
    o->x = row->x;
}
'''


def test_row_pointer_is_read_on_the_line_before():
    children = nested_row_pointer_local.variants(SOURCE, 'f')
    assert len(children) == 1
    family, text = children[0]
    assert family == 'nested_row_pointer_local'
    assert 'u8 *TABLE_row;' in text
    assert 'TABLE_row = TABLE[G]; row = &o->rows[TABLE_row[o->kind * 2]];' in text


def test_declarations_from_the_header():
    body = SOURCE.replace('extern u8 *TABLE[];\n', '')
    assert nested_row_pointer_local.variants(body, 'f', header='extern u8 *TABLE[4];')


def test_not_a_row_read_or_a_call_in_the_statement():
    assert not nested_row_pointer_local.variants(SOURCE.replace('TABLE[G][o->kind * 2]', 'TABLE[G]'), 'f')
    assert not nested_row_pointer_local.variants(SOURCE.replace('o->kind * 2', 'g(o)'), 'f')
    assert not nested_row_pointer_local.variants(SOURCE.replace('TABLE[G]', 'TABLE[G++]'), 'f')
    assert not nested_row_pointer_local.variants(SOURCE.replace('row = &', 'if (o) row = &'), 'f')

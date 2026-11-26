"""Byte tables walked by address arithmetic, written as arrays and a record (an 80-instruction table loader)."""
from decomprepair.linear_subscript_view import FAMILY, REPAIR, variants

SOURCE = """extern u8 D_80100000[];
extern u8 D_80100100[];
extern u8 D_80100200[];

void load(u8 which)
{
    s32 i;
    s32 j;
    u8 *base;
    u8 *row;
    u8 *dst;

    base = D_80100000;
    row = D_80100100 + which * 0xE0;
    for (i = 0; i < 0xE; i++) {
        dst = row + i * 0x10;
        for (j = 0; j < 8; j++) {
            *(u16 *)(dst + j * 2) = *(u16 *)(base + i * 0x10 + 0x1C + j * 2);
        }
    }
    for (i = 0; i < 8; i++) {
        D_80100200[which * 0x110 + i * 0x22] = base[i + 0x14];
        base[i + 4] = 0;
    }
}
"""


def test_every_table_is_written_as_its_array_and_the_source_as_a_record_in_one_child():
    family, child = variants(SOURCE, 'load')[0]
    assert family == FAMILY
    assert 'extern u16 D_80100100[][14][8];' in child
    assert 'extern u8 D_80100200[][8][34];' in child
    assert '    u8 m4[16];\n    u8 m14[8];\n    u16 m1C[16][8];\n} View_D_80100000;' in child
    assert 'View_D_80100000 *base;' in child and 'base = (View_D_80100000 *) D_80100000;' in child
    assert 'D_80100100[which][i][j] = base->m1C[i][j];' in child
    assert 'D_80100200[which][i][0] = base->m14[i];' in child
    assert 'base->m4[i] = 0;' in child
    assert 'dst' not in child and 'row' not in child


def test_each_table_alone_is_also_offered():
    children = [child for _, child in variants(SOURCE, 'load')]
    assert any('[][8][34]' in c and 'View_D_80100000' not in c for c in children)


def test_a_table_whose_address_is_passed_on_is_left_alone():
    escaped = SOURCE.replace('base[i + 4] = 0;', 'use(D_80100200);')
    assert all('D_80100200[][' not in child for _, child in variants(escaped, 'load'))


def test_an_index_written_between_a_row_pointer_and_its_read_keeps_the_pointer():
    moved = SOURCE.replace('        for (j = 0; j < 8; j++) {\n', '        i += 0;\n        for (j = 0; j < 8; j++) {\n')
    assert all('D_80100100[][' not in child for _, child in variants(moved, 'load'))


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and REPAIR['families'] == (FAMILY,)

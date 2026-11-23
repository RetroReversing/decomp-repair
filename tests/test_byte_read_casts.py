"""`(u8)` at the reads of a wide local after the first (a scroll window's scale, 200 -> 0)."""
from decomprepair.byte_read_casts import FAMILY, variants

HEADER = """typedef struct { char pad[9]; u8 height; } Row;
typedef struct { Row *rows; u8 scale, limit, top; s16 delta; } Window;
"""
SOURCE = """void draw_rows(Window *w, Row *row)
{
    s32 scale;
    s32 h, y;

    scale = w->scale;
    h = scale * row->height;
    if (y + h >= 3 - scale && y < 5 + scale * w->limit)
        go(row);
}
"""


def children(source=SOURCE, header=HEADER):
    return [text for family, text in variants(source, 'draw_rows', header) if family == FAMILY]


def test_the_reads_after_the_first_are_cast_to_the_byte_and_all_reads_in_a_second_child():
    later, every = children()
    assert 'h = scale * row->height;' in later
    assert 'if (y + h >= 3 - (u8)scale && y < 5 + (u8)scale * w->limit)' in later
    assert 'h = (u8)scale * row->height;' in every and '3 - (u8)scale' in every


def test_a_member_that_is_not_a_byte_is_left_alone():
    assert children(SOURCE.replace('scale = w->scale;', 'scale = w->delta;')) == []


def test_a_local_written_twice_is_left_alone():
    assert children(SOURCE.replace('    h = scale * row->height;', '    h = scale * row->height;\n    scale = 2;')) == []


def test_one_read_alone_has_nothing_to_cast():
    assert children(SOURCE.replace(' && y < 5 + scale * w->limit', '').replace('h = scale * row->height;', 'h = row->height;')) == []


def test_a_narrow_local_is_left_alone():
    assert children(SOURCE.replace('s32 scale;', 'u8 scale;')) == []

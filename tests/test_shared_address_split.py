"""A stack's end that is also the next buffer's start, written from a lower symbol (a gcc 2.8.1 start-up)."""
from decomprepair import shared_address_split as t

SOURCE = '''typedef unsigned char u8;
extern u8 D_80084AF0[];
void f(s32 pri)
{
    createQueue(&q, D_80084AF0, 1);
    createThread(&thread, 1, entry, 0, D_80084AF0, pri);
}
'''


def test_each_use_alone_is_written_from_a_lower_symbol_latest_first():
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert len(out) == 2
    assert 'createThread(&thread, 1, entry, 0, (D_80083AF0 + 0x1000), pri);' in out[0]
    assert 'createQueue(&q, D_80084AF0, 1);' in out[0]
    assert 'extern u8 D_80083AF0[];\nextern u8 D_80084AF0[];' in out[0]
    assert 'createQueue(&q, (D_80083AF0 + 0x1000), 1);' in out[1]


def test_a_taken_symbol_name_moves_to_the_next_size():
    source = 'extern u8 D_80083AF0[];\n' + SOURCE.replace('&q,', 'D_80083AF0,')
    assert '(D_800842F0 + 0x800)' in t.variants(source, 'f')[0][1]


def test_a_single_use_or_indexed_array_is_left_alone():
    assert t.variants(SOURCE.replace('createQueue(&q, D_80084AF0, 1);', ''), 'f') == []
    assert t.variants(SOURCE.replace('&q, D_80084AF0,', '&q, D_80084AF0[1],'), 'f') == []

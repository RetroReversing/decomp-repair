from decomprepair.narrow_table_addend import FAMILY, variants, widen

SOURCE = '''extern s16 delta_table[];
extern u16 plain_table[];

void f(char *obj, u16 *rec)
{
    u16 i;

    i = rec[20];
    (*(u16 *)((char *)(obj) + 0x1BC)) += delta_table[i * 2];
    (*(u16 *)((char *)(obj) + 0x1BE)) += plain_table[i * 2];
    (*(u8 *)((char *)(obj) + 0x1C0)) -= delta_table[i];
}
'''


def made(source=SOURCE, header=''):
    return [text for family, text in variants(source, 'f', header) if family == FAMILY]


def test_a_signed_table_read_goes_through_a_wide_local():
    texts = made()
    assert len(texts) == 3 and 's32 __repair_wide1;' in texts[0] and 's32 __repair_wide2;' in texts[0]
    everything = texts[0]
    assert '__repair_wide1 = delta_table[i * 2];' in everything
    assert '(*(u16 *)((char *)(obj) + 0x1BC)) += __repair_wide1;' in everything
    assert '__repair_wide2 = delta_table[i];' in everything and '-= __repair_wide2;' in everything
    assert '+= plain_table[i * 2];' in everything
    assert made()[1].count('__repair_wide') == 3


def test_a_table_the_header_declares_counts_and_an_unsigned_one_does_not():
    bare = SOURCE.replace('extern s16 delta_table[];\n', '')
    assert not made(bare)
    assert made(bare, header='extern s16 delta_table[];\n')


def test_a_call_in_the_index_or_a_wider_destination_stays():
    called = made(SOURCE.replace('delta_table[i * 2]', 'delta_table[pick(i)]'))
    assert called and all('+= delta_table[pick(i)];' in text for text in called)
    wider = SOURCE.replace('(*(u16 *)((char *)(obj) + 0x1BC))', '(*(u32 *)((char *)(obj) + 0x1BC))')
    assert all('+= delta_table[i * 2];' in text for text in made(wider))


def test_the_assignment_inside_the_use_is_kept_whole():
    inline = SOURCE.replace('((char *)(obj) + 0x1BC)', '((char *)(p = obj + (i * 2)) + 0x1BC)')
    text = widen(inline, 'f')
    assert '(*(u16 *)((char *)(p = obj + (i * 2)) + 0x1BC)) += __repair_wide1;' in text

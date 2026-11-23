from decomprepair.global_argument_address_stage import FAMILY, variants

HEADER = '''extern s32 gParents;
extern s32 *gPointer;
extern u8 gTable[];
'''
SOURCE = '''void f(u8 *t, u8 *a)
{
    s32 id;
    if (*(u32 *) (a + 0x60) & 8) {
        id = lookup(*(u16 *) (t + 0x48));
        caption(0, gParents, id, -1, 1, 0x3C);
        sound(9, a + 0x24);
    }
}
'''


def made(source=SOURCE, header=HEADER):
    return [text for family, text in variants(source, 'f', header) if family == FAMILY]


def test_the_global_is_read_through_an_address_taken_before_the_first_call():
    texts = made()
    assert len(texts) == 1
    text = texts[0]
    assert text.index('s32 *global_address = &gParents;') < text.index('id = lookup(') < text.index('caption(0, *global_address, id, -1, 1, 0x3C);')
    assert text.count('gParents') == 1 and 'sound(9, a + 0x24);' in text


def test_pointers_arrays_unknown_names_and_unrelated_calls_stay():
    assert not made(SOURCE.replace('gParents', 'gPointer'))
    assert not made(SOURCE.replace('gParents', 'gTable'))
    assert not made(SOURCE, '')
    assert not made(SOURCE.replace('id, -1', '0, -1'))

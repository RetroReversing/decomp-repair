from decomprepair.load_stage_before_store import FAMILIES, variants

HEADER = '''extern void *gChased;
extern s32 *gOrder;
extern u8 gDone[];
'''
SOURCE = '''void f(u8 *t, u8 *a)
{
    s32 n;
    n = 1;
    gChased = NULL;
    if (*(u16 *) (t + 0x36)) gDone[*(u16 *) (t + 0x36)] = 1;
    *(s16 *) (a + 0x7A) = 2;
    link(*gOrder, a, 0);
    done();
}
'''


def made(family, source=SOURCE, header=HEADER):
    return [text for fam, text in variants(source, 'f', header) if fam == family]


def test_the_index_read_before_the_store():
    texts = made(FAMILIES[0])
    assert len(texts) == 1
    text = texts[0]
    assert text.index('s32 staged = *(u16 *) (t + 0x36);') < text.index('gChased = NULL;')
    assert 'if (staged) gDone[staged] = 1;' in text


def test_a_pointer_read_before_the_store():
    texts = made(FAMILIES[1])
    assert len(texts) == 1
    text = texts[0]
    assert text.index('s32 *probe = gOrder;') < text.index('*(s16 *) (a + 0x7A) = 2;') < text.index('link(*probe, a, 0);')
    assert 'link(*gOrder' not in text


def test_a_store_the_read_depends_on_a_local_store_or_an_undeclared_pointer_stays():
    assert not made(FAMILIES[0], SOURCE.replace('gChased = NULL;', 'n = 2;'))
    assert not made(FAMILIES[0], SOURCE.replace('gChased = NULL;', 'gChased = *(u16 *) (t + 0x36);'))
    assert not made(FAMILIES[1], SOURCE, '')
    assert not made(FAMILIES[1], SOURCE.replace('*(s16 *) (a + 0x7A) = 2;', 'n = 2;'))

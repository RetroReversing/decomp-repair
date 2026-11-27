"""A low-bits mask of an unsigned value as a remainder by a power of two."""
from decomprepair import registry
from decomprepair import unsigned_mask_modulo as p

SOURCE = '''void put(u16 c, s32 w, s32 n)
{
    u16 s;

    s = (c & 0xF) * w;
    s = (n & 0xF) * w;
    use(s, c & 0x3E);
}
'''


def test_an_unsigned_mask_becomes_a_remainder():
    [(family, text)] = p.variants(SOURCE, 'put')
    assert family == p.FAMILY
    assert 's = (c % 16) * w;' in text and 's = (n & 0xF) * w;' in text


def test_the_remainder_becomes_a_mask_and_it_is_registered():
    [(_, text)] = p.variants(SOURCE.replace('(c & 0xF)', '(c % 16)'), 'put')
    assert '(c & 0xf)' in text
    assert any(p.FAMILY in repair.families for repair in registry.declared())

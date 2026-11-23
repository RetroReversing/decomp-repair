from decomprepair.shared_product_local import FAMILY, variants

SOURCE = '''void f(u8 *a, u32 i)
{
    if (i) {
        *(f32 *) (a + 0x28) = *(f32 *) (a + 0x28) + (f32) tab[i & 0x7F] * 0.0000078125f;
    }
    *(f32 *) (a + 0x44) = *(f32 *) (a + 0x44) + (f32) tab[(i >> 2) & 0x7F] * 0.0015625f;
    *(f32 *) (a + 0x3C) = *(f32 *) (a + 0x3C) + 1.0f;
}
'''


def made(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_every_product_update_goes_through_one_local():
    texts = made()
    assert len(texts) == 1
    text = texts[0]
    assert text.count('shared_product =') == 2
    assert text.index('f32 shared_product;') < text.index('shared_product = (f32) tab[i & 0x7F] * 0.0000078125f;')
    assert '*(f32 *) (a + 0x28) = *(f32 *) (a + 0x28) + shared_product;' in text
    assert '*(f32 *) (a + 0x44) = *(f32 *) (a + 0x44) + shared_product;' in text
    assert '0x3C) + 1.0f;' in text  # a sum without a product stays


def test_one_update_or_mixed_types_or_a_taken_name_stay():
    one = SOURCE.replace('*(f32 *) (a + 0x44) = *(f32 *) (a + 0x44) + (f32) tab[(i >> 2) & 0x7F] * 0.0015625f;', 'g();')
    assert not made(one)
    mixed = SOURCE.replace('*(f32 *) (a + 0x44) = *(f32 *) (a + 0x44)', '*(f64 *) (a + 0x44) = *(f64 *) (a + 0x44)')
    assert not made(mixed)
    assert not made(SOURCE.replace('{\n    if', '{\n    f32 shared_product;\n    if', 1))

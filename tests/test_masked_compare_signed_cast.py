from decomprepair.masked_compare_signed_cast import FAMILY, variants

SOURCE = '''void f(void *p, s32 k)
{
    if (((((u16) *(u16 *) ((char *) p + table(k) * 0xC)) >> 2) & 7) < 2)
    {
        use(p);
    }
    if ((k & 0xFF) < 5)
    {
        use(k);
    }
}
'''


def casts(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_a_deeply_nested_masked_field_beside_a_compare_is_cast_to_a_halfword():
    texts = casts()
    assert len(texts) == 3, 'each site, and both together'
    assert any('if ((s16) ((((u16) *(u16 *) ((char *) p + table(k) * 0xC)) >> 2) & 7) < 2)' in t for t in texts)
    assert any('(s16) (k & 0xFF) < 5' in t for t in texts)
    assert sum(1 for t in texts if t.count('(s16)') == 2) == 1


def test_a_mask_wider_than_a_halfword_or_an_operator_that_is_not_a_compare_is_left_alone():
    assert not casts(SOURCE.replace('& 7) < 2', '& 0x1FFFF) < 2').replace('(k & 0xFF) < 5', 'k == 5'))
    assert not casts(SOURCE.replace(') < 2)', ') == 2)').replace('(k & 0xFF) < 5', 'k == 5'))


def test_an_operand_already_cast_is_left_alone():
    assert len(casts(SOURCE.replace('if ((k & 0xFF) < 5)', 'if ((s16) (k & 0xFF) < 5)'))) == 1

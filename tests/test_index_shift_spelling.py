

def test_a_parenthesised_operand_and_a_parenthesised_product_are_spelled_as_shifts():
    # An effect spawner (KMC GCC 2.7.2): `addu $v0, $s2, $v0` for both scaled record reads came only with the shifts,
    # 125 -> 115 with both.
    from decomprepair import index_shift_spelling as m
    source = ('void f(void *s, u32 k, void *a)\n{\n'
              '    g(*((s16 *) (((char *) (s + (k * 2))) + 0x1BC)));\n'
              '    g(*((u8 *) (((char *) (s + ((*((s8 *) (((char *) a) + 0xE))) * 8))) + 0x1FD)));\n}\n')
    out = [text for _, text in m.variants(source, 'f')]
    assert any('(s + ((k << 1)))' in o or '(s + (k << 1))' in o for o in out)
    assert any('(s + (((*((s8 *) (((char *) a) + 0xE))) << 3)))' in o for o in out)
    both = [o for o in out if '<< 1' in o and '<< 3' in o]
    assert both

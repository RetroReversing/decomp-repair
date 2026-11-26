from decomprepair.call_arg_result_hoist import FAMILY, variants

SOURCE = '''void f(s32 arg0) {
    void *v0;

    v0 = alloc();
    *(s16 *) v0 = 0x1A;
    *(s32 *) ((s8 *) v0 + 0x14) = big(arg0 + 0xD4, &tab, 0x78, 0x78, 0, 1, 0xFF, 0xBD, 0, 0xFA, (rnd(8) + 0x26) & 0xFF);
}
'''


def children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_masked_nested_call_is_computed_just_before_the_call():
    s32, u8, dropped = children()
    assert '    void *v0;\n    s32 t;\n' in s32
    assert '    t = rnd(8) + 0x26;\n    *(s32 *) ((s8 *) v0 + 0x14) = big(' in s32
    assert '0xFA, t & 0xFF);' in s32
    assert '    u8 t;\n' in u8 and '0xFA, t & 0xFF);' in u8
    assert '0xFA, t);' in dropped and '    u8 t;\n' in dropped


def test_an_unmasked_sum_and_a_plain_statement_call():
    src = SOURCE.replace('(rnd(8) + 0x26) & 0xFF', 'rnd(8) - 3').replace('*(s32 *) ((s8 *) v0 + 0x14) = big', 'big')
    (child,) = children(src)
    assert '    t = rnd(8) - 3;\n    big(' in child and '0xFA, t);' in child


def test_a_short_call_or_a_bare_result_is_left_alone():
    assert not children(SOURCE.replace('arg0 + 0xD4, &tab, 0x78, 0x78, 0, 1, 0xFF, 0xBD, 0, 0xFA', '1, 2, 3'))
    assert not children(SOURCE.replace('(rnd(8) + 0x26) & 0xFF', 'rnd(8)'))
    assert not children(SOURCE.replace('rnd(8)', 'rnd(i++)'))


def test_the_local_name_is_fresh():
    assert 'u8 t_;' in children(SOURCE.replace('s32 arg0', 's32 t'))[1]

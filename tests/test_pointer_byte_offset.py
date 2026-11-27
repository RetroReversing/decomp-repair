"""A word pointer stepped by bytes is written through a byte pointer."""
from decomprepair import registry
from decomprepair.pointer_byte_offset import FAMILY, variants

SOURCE = '''void f(void) {
    s32 *base;
    s32 *var_a0;
    s16 *half;
    s32 n;
    if ((*(base = &D_1)) > 3) {
        var_a0 = base - 0xC0;
        g(var_a0, half + 8, n + 4);
    }
}
'''


def children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_a_word_pointer_stepped_by_a_literal_becomes_a_byte_step():
    texts = children()
    assert 'var_a0 = (s32 *) ((s8 *) base - 0xC0);' in texts[0]


def test_each_site_and_all_together_and_not_integers():
    texts = children()
    assert len(texts) == 3
    assert 'g(var_a0, (s16 *) ((s8 *) half + 8), n + 4);' in texts[-1]
    assert texts[-1].count('(s8 *)') == 2


def test_a_byte_pointer_or_an_undeclared_name_is_left_alone():
    assert not children(SOURCE.replace('s32 *base', 's8 *base').replace('s16 *half', 'u8 *half'))
    assert not children(SOURCE.replace('var_a0 = base - 0xC0', 'var_a0 = other - 0xC0').replace('half + 8', 'n'))


def test_declared_to_the_registry():
    assert any(r.module == 'pointer_byte_offset' for r in registry.declared())

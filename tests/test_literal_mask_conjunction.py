"""A mask that is the AND of two literals, written as the one the game used."""
import re

from decomprepair import registry
from decomprepair.literal_mask_conjunction import FAMILY, variants

CODE = '''typedef unsigned int u32;

u32 f(u32 colour)
{
    return (colour & 0xFF00) | ((colour >> 0x18) << 0x18) | (colour & (0xFF0000 & 0xFFFFu));
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_each_literal_is_offered_with_every_order_of_its_chain():
    kids = variants(CODE, 'f')
    assert {family for family, _ in kids} == {FAMILY}
    texts = [squash(child) for _, child in kids]
    assert len(texts) == 12
    assert 'return (colour & 0xFF00) | ((colour >> 0x18) << 0x18) | (colour & 0xFF0000);' in texts[0] or \
        'return (colour & 0xFF00) | ((colour >> 0x18) << 0x18) | colour & 0xFF0000;' in texts[0]
    assert any('return (colour >> 0x18) << 0x18 | colour & 0xFF0000 | colour & 0xFF00;' in text or
               'return ((colour >> 0x18) << 0x18) | (colour & 0xFF0000) | (colour & 0xFF00);' in text for text in texts)
    assert not any('0xFFFFu' in text for text in texts[:6])
    assert all('0xFF0000' not in text for text in texts[6:])


def test_a_chain_of_more_than_three_terms_keeps_its_order():
    code = CODE.replace('(colour & 0xFF00) |', '(colour & 0xFF00) | (colour & 0xFF) |')
    assert len(variants(code, 'f')) == 2


def test_a_conjunction_that_equals_one_of_its_operands_is_left_alone():
    assert variants(CODE.replace('0xFF0000 & 0xFFFFu', '0xFFFF & 0xFFu'), 'f') == []
    assert variants(CODE.replace('(0xFF0000 & 0xFFFFu)', '0xFF0000'), 'f') == []


def test_a_conjunction_of_variables_is_left_alone():
    assert variants(CODE.replace('0xFF0000 & 0xFFFFu', 'mask & 0xFFFFu'), 'f') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []

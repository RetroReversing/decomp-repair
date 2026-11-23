"""A byte copy of a word that the later code masks again, and sets again where it cannot change."""
import re

from decomprepair import registry
from decomprepair.narrow_copy_reuse import FAMILY, variants

CODE = '''typedef unsigned char u8;
typedef unsigned int u32;
extern void g(void);
extern void put(u32);

void f(u32 *p, int n)
{
    u32 word;
    u8 low;
    word = *p;
    low = (u8) word;
    if (low >= 5U)
    {
        low = word & 0xFF;
        if (n == 1)
        {
            g();
            low = ((u32) word) & 0xFF;
        }
        if (low)
        {
            put((word & 0xFF0000) | (word & 0xFF));
        }
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def texts():
    return [squash(child) for _, child in variants(CODE, 'f')]


def test_the_three_edits_are_offered_alone_and_together():
    kids = variants(CODE, 'f')
    assert {family for family, _ in kids} == {FAMILY}
    assert len(kids) == 7
    both = [text for text in texts() if 'low = word & 0xFF;' not in text and 'if ((word & 0xFF))' in text and '| low)' in text]
    assert len(both) == 1
    assert 'low = (u8) word;' in both[0] and 'g(); } ' in both[0]


def test_dropping_the_reassignments_alone_keeps_the_test_and_the_expression():
    only = [text for text in texts() if 'low = word & 0xFF;' not in text and 'if (low)' in text and '| (word & 0xFF)' in text]
    assert len(only) == 1


def test_the_word_assigned_again_or_taken_by_address_is_left_alone():
    assert variants(CODE.replace('put(', 'word = 1; put('), 'f') == []
    assert variants(CODE.replace('put(', 'g(&word); put('), 'f') == []


def test_a_function_without_the_copy_has_no_proposals():
    assert variants(CODE.replace('low = (u8) word;', 'low = 3;'), 'f') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []

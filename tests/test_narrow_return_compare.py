"""A narrow callee declaration and an offset compare, written together as the int the game compared."""
import re

from decomprepair import registry
from decomprepair.narrow_return_compare import FAMILY, variants

CODE = '''typedef signed char s8;
typedef int s32;
volatile short randomIntBelow();
extern s32 gSlot;
extern s8 gCount;

void pick(void)
{
    s8 count;
    s32 pick;
    count = gCount;
    if (3 < (count + 1)) {
        pick = randomIntBelow(count - 1);
        gSlot = pick * 0x18;
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_declaration_and_the_compare_come_together_first_then_each_alone():
    children = [squash(text) for _, text in variants(CODE, 'pick')]
    assert len(children) == 3
    both, declaration, compare = children
    assert 's32 randomIntBelow();' in both and 'if (count >= 3)' in both
    assert 's32 randomIntBelow();' in declaration and 'if (3 < (count + 1))' in declaration
    assert 'volatile short randomIntBelow();' in compare and 'if (count >= 3)' in compare


def test_the_mirrored_and_subtracted_compares_fold():
    for before, after in (('(count + 1) > 3', 'count >= 3'), ('3 <= (count + 1)', 'count >= 2'),
                          ('(count - 2) < 5', 'count < 7'), ('9 > (count - 1)', 'count < 10')):
        children = [squash(text) for _, text in variants(CODE.replace('3 < (count + 1)', before), 'pick')]
        assert any(f'if ({after})' in text for text in children), (before, after)


def test_an_unsigned_local_or_an_uncalled_callee_is_left_alone():
    unsigned = CODE.replace('s8 count;', 'unsigned char count;')
    assert all('count >= 3' not in squash(text) for _, text in variants(unsigned, 'pick'))
    uncalled = CODE.replace('randomIntBelow(count - 1)', 'gCount')
    assert all('s32 randomIntBelow' not in squash(text) for _, text in variants(uncalled, 'pick'))


def test_a_wide_declaration_has_no_proposal_of_its_own():
    children = [squash(text) for _, text in variants(CODE.replace('volatile short', 's32'), 'pick')]
    assert len(children) == 1 and 'if (count >= 3)' in children[0]


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []

"""A constant folded into a sum with a loaded global, computed first in a temporary of its own."""
import re

from decomprepair import registry
from decomprepair.term_split_local import FAMILY, variants

CODE = '''typedef int s32;
extern s32 gHeight;
extern s32 gRow;

void f(s32 t)
{
    s32 v;
    if (t < 0) {
        v = t - 1 + gHeight;
    } else if (t > 7) {
        v = t + 1 - gHeight;
    } else {
        v = t;
    }
    gRow = v;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_every_site_gets_a_temporary_of_its_own_in_one_child():
    first, *rest = variants(CODE, 'f')
    text = squash(first[1])
    assert first[0] == FAMILY and len(rest) == 2
    assert 'term0 = t - 1; v = term0 + gHeight;' in text
    assert 'term1 = t + 1; v = term1 - gHeight;' in text
    assert 's32 term0; s32 term1;' in text


def test_each_site_is_also_proposed_alone():
    _, one, two = variants(CODE, 'f')
    assert 'term0 = t - 1;' in squash(one[1]) and 'term1' not in squash(one[1])
    assert 'v = t - 1 + gHeight;' in squash(two[1]) and 'term0' not in squash(two[1])


def test_a_sum_without_a_loaded_global_is_left_alone():
    assert variants(CODE.replace('gHeight;\n    } else if', 'gRow;\n    } else if').replace('+ 1 - gHeight', '+ 1 - t'), 'f') != []
    assert variants('typedef int s32;\nvoid f(s32 t, s32 u)\n{\n    s32 v;\n    v = t - 1 + u;\n    g(v);\n}\n', 'f') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []

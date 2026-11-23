"""m2c's `else if` chain with a range arm that repeats the default, written as the `switch` it came from."""
import re

from decomprepair import registry
from decomprepair.else_if_chain_switch import FAMILY, variants

CODE = '''typedef int s32;
s32 pick(s32 mode, s32 n)
{
    s32 v;
    if (mode == 1)
        v = n + (n * 4 + 5);
    else if (mode < 2)
        v = n + 5;
    else if (mode == 2)
        v = n * 3 + (n + 2);
    else if (mode == 3)
        v = n * 3 + (n + 2) + n * 4;
    else
        v = n + 5;
    return v * 4;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_chain_becomes_a_switch_with_the_low_values_in_front_of_default():
    children = variants(CODE, 'pick')
    assert [family for family, _ in children] == [FAMILY, FAMILY]
    labelled, plain = (squash(text) for _, text in children)
    assert 'switch (mode)' in labelled and 'if (mode' not in labelled
    assert 'case 1: v = n + (n * 4 + 5); break;' in labelled
    assert 'case 3: v = n * 3 + (n + 2) + n * 4; break;' in labelled
    assert 'case 0: default: v = n + 5; break;' in labelled
    assert 'case 0:' not in plain and 'default: v = n + 5; break;' in plain
    assert 'return v * 4;' in labelled


def test_an_arm_that_differs_from_the_default_or_a_break_is_left_alone():
    assert variants(CODE.replace('v = n + 5;\n    else if (mode == 2)', 'v = n + 6;\n    else if (mode == 2)'), 'pick') == []
    assert variants(CODE.replace('v = n * 3 + (n + 2);', 'break;'), 'pick') == []


def test_a_chain_over_two_variables_or_without_a_range_arm_is_left_alone():
    assert variants(CODE.replace('mode == 3', 'n == 3'), 'pick') == []
    plain = CODE.replace('    else if (mode < 2)\n        v = n + 5;\n', '')
    assert variants(plain, 'pick') == []


def test_the_module_declares_itself_to_the_registry():
    assert any(repair.function is variants or getattr(repair, 'variants', None) is variants
               for repair in registry.declared() if getattr(repair, 'families', ()) == (FAMILY,))

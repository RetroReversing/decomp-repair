"""An `if (a < b) { A } else { B }` written with the opposite test and the arms in the other order."""
import re

from decomprepair import registry
from decomprepair.else_if_arm_swap import FAMILY, variants

CODE = '''typedef int s32;
extern s32 gHeight;
extern s32 gRow;

void f(s32 t)
{
    s32 v;
    if (t < 0) {
        v = t - 1;
    } else if (gHeight - 1 < t) {
        v = t + 1 - gHeight;
    } else {
        v = t;
    }
    gRow = v;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def texts(code):
    return [squash(text) for family, text in variants(code, 'f') if family == FAMILY]


def test_the_last_else_if_takes_the_inverse_test_and_the_arms_exchanged():
    found = texts(CODE)
    assert any('else if (gHeight - 1 >= t) { v = t; } else { v = t + 1 - gHeight; }' in text for text in found)
    assert any('else if (t <= gHeight - 1) { v = t; } else { v = t + 1 - gHeight; }' in text for text in found)


def test_the_outer_if_is_swapped_too_and_nothing_else_changes():
    found = texts(CODE)
    assert all('if (t < 0) { v = t - 1; } else if' in text for text in found)  # the outer `else if` has no braced else
    assert all('gRow = v;' in text and text.count('v = ') == 3 for text in found)


def test_a_compound_test_or_an_if_without_an_else_is_left_alone():
    compound = CODE.replace('if (t < 0) {', 'if (t < 0 && t > -9) {').replace('} else if (gHeight - 1 < t) {', '} else if (gHeight - 1 < t || t == 7) {')
    assert texts(compound) == []
    assert variants('typedef int s32;\nvoid f(s32 t)\n{\n    s32 v;\n    if (t < 0) {\n        v = 1;\n    }\n}\n', 'f') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []

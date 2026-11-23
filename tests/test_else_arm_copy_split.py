"""A copy that the `then` arm overwrites, moved into the `else` arm, with the source's later reuse of it split off."""
import re

from decomprepair import registry
from decomprepair.else_arm_copy_split import FAMILY, variants

CODE = '''typedef int s32;
extern s32 gWidth;
extern s32 gOut;

void f(s32 c)
{
    s32 x, y;
    x = c + 1;
    gOut = x;
    y = x;
    if (x < 0) {
        y = x + gWidth;
    } else if (gWidth < y) {
        y -= gWidth;
    }
    gOut = y;
    x = gWidth * 3;
    gOut = x;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_copy_opens_the_else_arm_and_the_later_value_gets_a_local_of_its_own():
    first, sink, split = [squash(text) for _, text in variants(CODE, 'f')]
    assert 'gOut = x; y = x; if' not in first
    assert 'else { y = x; if (gWidth < y) { y -= gWidth; } }' in first
    assert 's32 x_next;' in first and 'x_next = gWidth * 3; gOut = x_next;' in first
    assert 'x_next' not in sink and 'else { y = x;' in sink
    assert 'y = x; if (x < 0)' in split and 'x_next = gWidth * 3;' in split


def test_a_plain_else_takes_the_copy_as_its_first_statement():
    code = CODE.replace('} else if (gWidth < y) {\n        y -= gWidth;\n    }', '} else {\n        y -= gWidth;\n    }')
    assert any('else { y = x; y -= gWidth; }' in squash(text) for _, text in variants(code, 'f'))


def test_a_then_arm_that_reads_the_copy_or_a_global_target_is_left_alone():
    assert variants(CODE.replace('y = x + gWidth;', 'y = y + gWidth;'), 'f') == []
    assert variants(CODE.replace('y = x;\n    if', 'gOut = x;\n    if'), 'f') == []
    assert variants(CODE.replace('    } else if (gWidth < y) {\n        y -= gWidth;\n    }', '    }'), 'f') == []


def test_the_later_value_is_not_split_when_it_reads_the_old_one():
    children = [squash(text) for _, text in variants(CODE.replace('x = gWidth * 3;', 'x = x * 3;'), 'f')]
    assert len(children) == 1 and 'x_next' not in children[0]


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []

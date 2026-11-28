"""A name read back under the test that fixed its value, written as the number."""
from decomprepair import guard_value_literal as literal
from decomprepair import registry

SOURCE = '''void check(void)
{
    if (gReady == 1) {
        if (find() == 5) {
            gOut = (s32) gReady;
            gFull = 0;
        }
    }
    gLast = gReady;
}
'''


def children(source=SOURCE):
    found = literal.variants(source, 'check')
    assert all(family == literal.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_copy_inside_the_arm_becomes_the_number():
    child, = children()
    assert 'gOut = 1;' in child
    assert 'gLast = gReady;' in child  # outside the arm nothing is known


def test_the_else_arm_of_an_inequality():
    child, = children('void check(void)\n{\n    if (gReady != 2) {\n        f();\n    } else {\n        gOut = gReady;\n    }\n}\n')
    assert 'gOut = 2;' in child


def test_an_arm_that_writes_the_name_declines():
    assert children(SOURCE.replace('gFull = 0;', 'gReady = 0;')) == []
    assert children(SOURCE.replace('find()', 'find(&gReady)')) == []


def test_a_comparison_is_not_a_copy():
    assert children(SOURCE.replace('gOut = (s32) gReady;', 'gOut = gOther == gReady;')) == []


def test_the_family_is_registered():
    assert any(literal.FAMILY in repair.families for repair in registry.declared())

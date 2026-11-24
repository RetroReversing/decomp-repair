"""m2c's `(v == K1) || (v != K2)` written as a switch with a shared default (a 2,503-instruction update, 23368 -> 21908)."""
from decomprepair.eq_or_ne_switch import FAMILY, variants

SOURCE = """void pick(s32 hit)
{
    if (gFlag != 0) {
        gA = 0;
    } else if ((hit == 1) || (hit != 2)) {
        gA = gB;
    } else {
        gA = gC;
        gD = 0;
    }
}
"""

SWITCH = """    } else {
        switch (hit) {
        default:
        case 1:
            gA = gB;
            break;
        case 2:
            gA = gC;
            gD = 0;
            break;
        }
    }
}
"""


def test_the_else_if_becomes_a_switch_with_the_shared_default_first():
    found = variants(SOURCE, 'pick')
    assert [family for family, _ in found] == [FAMILY, FAMILY]
    assert found[0][1].endswith(SWITCH)
    assert found[0][1].startswith('void pick(s32 hit)\n{\n    if (gFlag != 0) {\n        gA = 0;\n')
    second = found[1][1]
    assert second.index('case 2:') < second.index('default:') < second.index('case 1:')


def test_a_plain_if_and_the_swapped_order_are_read_too():
    source = SOURCE.replace('    if (gFlag != 0) {\n        gA = 0;\n    } else if ((hit == 1) || (hit != 2)) {',
                            '    if ((hit != 2) || (hit == 1)) {')
    text = variants(source, 'pick')[0][1]
    assert text.startswith('void pick(s32 hit)\n{\n    switch (hit) {\n    default:\n    case 1:\n        gA = gB;\n        break;\n')


def test_equal_constants_or_a_missing_else_are_left_alone():
    assert variants(SOURCE.replace('hit != 2', 'hit != 1'), 'pick') == []
    no_else = 'void f(s32 v)\n{\n    if ((v == 1) || (v != 2)) {\n        g = 1;\n    }\n}\n'
    assert variants(no_else, 'f') == []

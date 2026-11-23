"""A switch's alias labels before default: removed, with the label below the lowest case (3871 -> 2451)."""
import re

from decomprepair.default_alias_label_reset import FAMILY, REPAIR, variants

CODE = '''extern int gMode;
extern void use(int);
void run(void)
{
    switch (gMode) {
    case 1:
        use(1);
        break;
    case 2:
        use(2);
        break;
    case 3:

    case 4:

    case 5:

    default:
        use(0);
        break;
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_aliases_go_with_and_without_the_neighbour_label():
    found = [text for family, text in variants(CODE, 'run') if family == FAMILY]
    assert len(found) == 2
    plain, neighbour = (squash(t) for t in found)
    assert 'break; default: use(0);' in plain and 'case 3:' not in plain and 'case 0:' not in plain
    assert 'break; case 0: default: use(0);' in neighbour and 'case 5:' not in neighbour


def test_the_other_labels_and_arms_are_untouched():
    for _, text in variants(CODE, 'run'):
        assert 'case 1:\n        use(1);' in text and 'case 2:\n        use(2);' in text
        assert text.count('default:') == 1 and text.endswith('}\n')


def test_a_label_already_below_the_lowest_is_not_added_twice():
    code = CODE.replace('    case 1:\n', '    case 0:\n    case 1:\n')
    found = [squash(text) for _, text in variants(code, 'run')]
    assert len(found) == 1 and 'case 0: case 1:' in found[0]


def test_labels_that_are_not_directly_before_default_are_left_alone():
    code = CODE.replace('    case 3:\n\n    case 4:\n\n    case 5:\n\n', '        break;\n')
    assert variants(code, 'run') == []
    only_aliases = '''void f(int x)\n{\n    switch (x) {\n    case 3:\n    case 4:\n    default:\n        g();\n    }\n}\n'''
    assert variants(only_aliases, 'f') == []


def test_a_nested_switch_is_skipped_and_the_function_must_exist():
    nested = CODE.replace('use(2);', 'switch (gMode) { case 7: default: use(2); }')
    assert variants(nested, 'run') == []
    assert variants(CODE, 'missing') == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and FAMILY in REPAIR['families']

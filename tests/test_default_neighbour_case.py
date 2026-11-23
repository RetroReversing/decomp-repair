"""A switch's default arm given the case label just below its lowest case."""
import re

from decomprepair.default_neighbour_case import FAMILY, variants

CODE = '''extern int gCount;
extern void use(int);
void run(void)
{
    switch (gCount) {
    default:
        use(0);
        break;
    case 2:
        use(1);
        break;
    case 3:
    case 4:
        use(2);
        break;
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_default_arm_gets_the_label_below_the_lowest_case():
    children = variants(CODE, 'run')
    assert [family for family, _ in children] == [FAMILY]
    assert 'switch (gCount) { case 1: default: use(0); break; case 2:' in squash(children[0][1])


def test_other_switches_are_left_alone():
    assert variants(CODE.replace('    default:\n        use(0);\n        break;\n', ''), 'run') == []
    assert 'case 0: default:' in squash(variants(CODE.replace('case 2:', 'case 1:'), 'run')[0][1])
    assert variants(CODE.replace('case 2:', 'case 1:').replace('    switch (gCount) {\n    default:', '    switch (gCount) {\n    case 0:\n    default:'), 'run') == []
    assert variants(CODE.replace('case 2:', 'case 0:').replace('case 3:', 'case 1:'), 'run') == []
    assert variants(CODE.replace('    case 3:\n    case 4:\n        use(2);\n        break;\n', ''), 'run') == []
    assert variants(CODE, 'missing') == []

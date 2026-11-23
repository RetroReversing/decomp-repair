"""A clamp written `(A > B) ? B : A` is rewritten into the orientation gcc 2.7.2's fold turns into a minimum."""
import re

from decomprepair.ternary_min_max_orientation import FAMILY, variants

CODE = '''#define MINL(a, b) (((a) > (b)) ? (b) : (a))
extern int G;
void f(int n)
{
    int lrs = n * 2;
    G = MINL(lrs + 1, 2047);
    G += (lrs > 2047) ? 2047 : lrs;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_clamp_in_the_function_and_in_the_macro_both_get_the_folding_orientation():
    children = variants(CODE, 'f')
    assert {family for family, _ in children} == {FAMILY}
    texts = [squash(text) for _, text in children]
    assert any('G += (lrs <= 2047) ? lrs : 2047;' in text for text in texts)
    assert any('G += (2047 < lrs) ? 2047 : lrs;' in text for text in texts)
    assert any('#define MINL(a, b) (((a) <= (b)) ? (a) : (b))' in text for text in texts)
    assert any('#define MINL(a, b) (((b) < (a)) ? (b) : (a))' in text for text in texts)
    assert len(children) == 4


def test_the_maximum_shapes_and_the_other_orientation_are_handled():
    code = 'extern int G;\nvoid f(int n)\n{\n    G = (n < 9) ? 9 : n;\n    G += (n >= 9) ? 9 : n;\n}\n'
    texts = [squash(text) for _, text in variants(code, 'f')]
    assert any('G = (n >= 9) ? n : 9;' in text for text in texts)
    assert any('G += (n < 9) ? n : 9;' in text for text in texts)


def test_arms_that_are_not_the_operands_floats_and_calls_are_left_alone():
    base = 'extern int G;\nextern int h(int);\nvoid f(int n)\n{\n    G = %s;\n}\n'
    for expr in ('(n > 9) ? 9 : n + 1', '(n > 9) ? n : 9', '(h(n) > 9) ? 9 : h(n)', '(n > 9.0f) ? 9.0f : n',
                 '(n > 9) ? 9 : (n = 3)'):
        assert variants(base % expr, 'f') == [], expr
    assert variants(CODE, 'missing') == []

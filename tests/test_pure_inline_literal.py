"""A pure one-line inline helper called on a literal is written as the literal."""
from decomprepair import pure_inline_literal as p

SOURCE = '''typedef short s16;
extern s16 a;
extern s16 b;
inline static int inline_fn(int arg0)
{
  return -arg0;
}

int f(void)
{
  int state = inline_fn(1);
  a = inline_fn(1);
  b = 3 - inline_fn(2);
  return state;
}
'''


def test_every_call_on_a_literal_is_folded_and_the_unused_helper_goes():
    (family, text), = p.variants(SOURCE, 'f')
    assert family == p.FAMILY
    assert 'int state = -1;' in text and 'a = -1;' in text and 'b = 3 - (-2);' in text
    assert 'inline_fn' not in text


def test_a_helper_still_called_elsewhere_stays():
    source = SOURCE + '\nint g(int x)\n{\n  return inline_fn(x);\n}\n'
    (_, text), = p.variants(source, 'f')
    assert 'inline_fn(int arg0)' in text and 'return inline_fn(x);' in text and 'a = -1;' in text


def test_arithmetic_wraps_like_the_helper_type():
    source = SOURCE.replace('int inline_fn(int arg0)', 'unsigned char inline_fn(unsigned char arg0)').replace('return -arg0', 'return ~arg0')
    (_, text), = p.variants(source, 'f')
    assert 'a = 254;' in text


def test_a_helper_that_does_more_than_arithmetic_is_left_alone():
    for body in ('return g(arg0);', 'a = arg0; return a;', 'return arg0 / 0;'):
        source = SOURCE.replace('return -arg0;', body)
        assert p.variants(source, 'f') == []


def test_a_call_with_a_variable_is_left_alone():
    assert p.variants(SOURCE.replace('inline_fn(1)', 'inline_fn(b)'), 'f')[0][1].count('inline_fn(b)') == 2

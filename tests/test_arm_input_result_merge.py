"""A block's input local folded into the result both arms of its `if` assign."""
from decomprepair.arm_input_result_merge import FAMILY, variants

# A sound-sequence interpreter's pitch commands (KMC GCC 2.7.2, N64): a halfword converted by sign, two commands.
TWO = '''void f(u8 *v)
{
  s32 a;
  s32 b;
  {
    s16 pitch = *((s16 *) (&G));
    if (pitch >= 0)
    {
      a = conv(pitch);
    }
    else
    {
      a = -conv(-pitch);
    }
  }
  v[0] = a;
  {
    s16 pitch = *((s16 *) (&G));
    if (pitch >= 0)
    {
      b = conv(pitch);
    }
    else
    {
      b = -conv(-pitch);
    }
  }
  v[1] = b;
}
'''


def _fold(text, var):
    return text.replace(f's16 pitch = *((s16 *) (&G));\n    if (pitch >= 0)\n    {{\n      {var} = conv(pitch);',
                        f'{var} = *((s16 *) (&G));\n    if ({var} >= 0)\n    {{\n      {var} = conv({var});', 1)


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_each_site_alone_and_both_together():
    one = _fold(TWO, 'a').replace('a = -conv(-pitch);', 'a = -conv(-a);')
    other = _fold(TWO, 'b').replace('b = -conv(-pitch);', 'b = -conv(-b);')
    both = _fold(one, 'b').replace('b = -conv(-pitch);', 'b = -conv(-b);')
    assert _children(TWO) == [one, other, both]


def test_a_truncating_input_is_left_alone():
    text = TWO.replace('s16 pitch = *((s16 *) (&G));', 's16 pitch = W;')
    assert _children(text) == []


def test_arms_assigning_different_results_are_left_alone():
    text = TWO.replace('a = -conv(-pitch);', 'b = -conv(-pitch);')
    assert len(_children(text)) == 1


def test_an_input_read_after_the_if_is_left_alone():
    text = TWO.replace('  }\n  v[0] = a;', '    v[2] = pitch;\n  }\n  v[0] = a;')
    assert len(_children(text)) == 1

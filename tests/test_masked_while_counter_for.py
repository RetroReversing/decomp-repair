"""masked_while_counter_for: a `while (1)` over a masked word counter, written as a narrow counter's `for` loop.

The source below is made up; it has the shape of a 97-instruction state machine that matched as a `for`."""
from decomprepair import masked_while_counter_for as family

SOURCE = '''extern u8 T[];
extern void g(s32);

inline static int low(s32 a)
{
  return a & 0xFF;
}

void f(void)
{
  s32 i;
  u32 x;
  i = 0;
  while (1)
  {
    x = low(i);
    if (T[x] == 0)
    {
      break;
    }
    i++;
    if (((u32) (i & 0xFF)) >= 6)
    {
      break;
    }
  }
  if (x < 3)
  {
    g(1);
  }
}
'''


def children(source):
    return [text for _, text in family.variants(source, 'f')]


def test_the_loop_becomes_a_for_over_a_byte():
    [text] = children(SOURCE)
    assert 'u8 i;' in text and 'for (i = 0; i < 6; i++)' in text
    assert 'T[i] == 0' in text and 'if (i < 3)' in text
    assert 'u32 x;' not in text and 'while' not in text


def test_the_spelled_mask_is_read_too():
    [text] = children(SOURCE.replace('x = low(i);', 'x = ((int) ((i) & 0xFF));'))
    assert 'for (i = 0; i < 6; i++)' in text and 'if (i < 3)' in text


def test_a_masked_read_in_the_body_needs_no_copy():
    source = SOURCE.replace('    x = low(i);\n', '').replace('T[x]', 'T[i & 0xFF]').replace('if (x < 3)', 'if (low(i) < 3)')
    [text] = children(source)
    assert 'T[i] == 0' in text and 'if (i < 3)' in text


def test_a_later_use_that_could_see_the_difference_is_refused():
    assert not children(SOURCE.replace('if (x < 3)', 'if (x < 9)'))
    assert not children(SOURCE.replace('g(1);', 'g(x);'))


def test_a_word_counter_read_elsewhere_is_refused():
    assert not children(SOURCE.replace('g(1);', 'g(i);'))


def test_a_continue_is_refused():
    assert not children(SOURCE.replace('    i++;\n', '    if (T[0]) continue;\n    i++;\n'))

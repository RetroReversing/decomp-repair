"""A loop's entry guard written as the counter's own first test."""
import re

from decomprepair.guard_counter_compare import variants

# Four loops of one function (GCC 2.7.2, KMC, N64): each guard `if (len != 0)` after `i = 0;` is the loop's first test
# `i < len`; the compiler leaves a dead compare pseudo for each, and each pseudo gets a spill slot in the frame.
BEFORE = '''void f(u16 *len, s32 *t)
{
  u32 i;
  u32 j;
  i = 0;
  if ((*len) != 0)
  {
    j = 0;
    do
    {
      t[j] += 1;
      i += 1;
      j += 6;
    }
    while (i < ((u16) (*len)));
  }
  i = 0;
  if ((*len) != 0)
  {
    j = 0;
    do
    {
      t[j] += 2;
      i += 1;
      j += 3;
    }
    while (i < ((u16) (*len)));
  }
}
'''


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def _all(text, name='f'):
    return [src for fam, src in variants(text, name) if fam == 'guard_counter_compare']


def test_one_guard_alone_and_all_together_are_proposed():
    found = [_squash(src) for src in _all(BEFORE)]
    assert any('if ((*len) > i) { j = 0;' in text and 'if ((*len) != 0)' in text for text in found)
    assert any('if ((*len) != 0)' not in text for text in found)


def test_a_guard_whose_loop_tests_something_else_is_left_alone():
    other = BEFORE.replace('while (i < ((u16) (*len)));', 'while (i < 10);')
    assert _all(other) == []


def test_a_guard_without_the_counter_init_before_it_is_left_alone():
    assert _all(BEFORE.replace('  i = 0;\n  if', '  t[0] = 0;\n  if')) == []


def test_other_processors_are_not_offered_it():
    assert variants(BEFORE, 'f', 'ppc') == []

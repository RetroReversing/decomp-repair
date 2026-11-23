"""The guard compare computed before the counter init the guarded body started with."""
import re

from decomprepair.guard_compare_first import variants

# The shape of a 16-bit/8-bit guarded loop pair (GCC 2.7.2, KMC, N64): `flag` is known zero from an earlier branch, the
# target compares it (`sltu $v0, $s3, $v0`) and fills the branch's delay slot with the counter's `move $s0, $zero`.
BEFORE = '''void f(u8 *a, u16 *len)
{
  u32 flag;
  u32 i;
  u32 n;
  flag = (*a) & 0x400;
  if (flag == 0)
  {
    if (flag < (*len))
    {
      i = 0;
      n = 0;
      do
      {
        n += i;
        i += 1;
      }
      while (i < (*len));
    }
    else
    {
      i = 0;
    }
  }
}
'''


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def _all(text, name='f'):
    return [src for fam, src in variants(text, name) if fam == 'guard_compare_first']


def test_the_compare_is_computed_first_and_the_init_stands_before_the_branch():
    found = _all(BEFORE)
    assert found
    text = _squash(found[0])
    assert 'guard_value = (flag < (*len)); i = 0; if (guard_value) { n = 0;' in text
    assert 'u32 guard_value;' in text


def test_nothing_is_proposed_when_the_counter_is_read_after_the_guard():
    after = BEFORE.replace('    else\n    {\n      i = 0;\n    }\n', '    else\n    {\n      n = i;\n    }\n')
    assert _all(after) == []


def test_nothing_is_proposed_when_the_condition_reads_the_counter():
    assert _all(BEFORE.replace('flag < (*len)', 'i < (*len)')) == []


def test_a_condition_with_a_call_is_left_alone():
    assert _all(BEFORE.replace('flag < (*len)', 'g(flag) < (*len)')) == []


def test_other_processors_are_not_offered_it():
    assert variants(BEFORE, 'f', 'ppc') == []


# The two arms of one `if` (the 16-bit and 8-bit variants of a loop) share one counter: a read of it in the other arm is
# reached only after that arm's own `i = 0;`, so both guards can be offered at once, as one child.
TWO_ARMS = '''void f(u8 *a, u16 *len, u8 *t)
{
  u32 flag;
  u32 i;
  u32 n;
  flag = (*a) & 0x400;
  if ((*t) & 4)
  {
    if (flag < (*len))
    {
      i = 0;
      do
      {
        n += i;
        i += 1;
      }
      while (i < (*len));
    }
  }
  else
  {
    if (flag < (*len))
    {
      i = 0;
      do
      {
        n += i * 2;
        i += 1;
      }
      while (i < (*len));
    }
  }
}
'''


def test_both_arms_are_rewritten_together_as_one_child():
    both = [src for src in _all(TWO_ARMS) if _squash(src).count('guard_value') >= 6]
    assert both
    text = _squash(both[0])
    assert 'guard_value = (flag < (*len)); i = 0; if (guard_value)' in text
    assert 'guard_value_2 = (flag < (*len)); i = 0; if (guard_value_2)' in text

import re

from decomprepair.joined_call_arm_split import FAMILY, variants

SOURCE = """s32 f(s32 mode, s32 wide)
{
  char *var_a0;
  char *var_a0_2;
  if (wide)
  {
    if (mode != 0)
    {
      var_a0 = first;
    }
    else
    {
      var_a0 = second;
    }
    apply(var_a0);
    return 1;
  }
  if (mode == 0)
  {
    var_a0_2 = third;
  }
  else
  {
    var_a0_2 = fourth;
  }
  apply(var_a0_2);
  return 0;
}
"""


def _found(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_both_picks_are_split_in_every_polarity_and_alone():
    found = _found()
    assert len(found) == 8  # four polarities of the pair, two of each pick
    wanted = [r'if \(mode != 0\)\W*apply\(first\);\W*else\W*apply\(second\);',
              r'if \(mode != 0\)\W*apply\(fourth\);\W*else\W*apply\(third\);']  # the second pick negated
    assert any(all(re.search(part, text) for part in wanted) and 'var_a0 =' not in text and 'var_a0_2 =' not in text
               for text in found)


def test_a_local_read_elsewhere_or_named_twice_in_the_call_is_left_alone():
    assert len(_found(SOURCE.replace('return 1;', 'return var_a0 != 0;'))) == 2
    assert len(_found(SOURCE.replace('apply(var_a0);', 'apply(var_a0, var_a0);'))) == 2

"""collapsed_guard_lifetime_merge: an identical-arm guard on an unassigned local collapsed, and two locals merged.

Synthetic shape of a 74-instruction KMC audio function (saved best 60; 110 with the collapse alone, 690 with the merge
alone, 0 with both): the flag local is read by a dead `if` before it is ever assigned."""
from decomprepair import collapsed_guard_lifetime_merge as c
from decomprepair import identical_arm_collapse_repairs, integer_lifetime_repairs

SOURCE = '''s32 note(s32 value);

s32 clamp(s16 *p, u32 word)
{
  s32 flag;
  s32 signed_v;
  s16 level;
  level = p[0] + (word >> 4);
  p[0] = level;
  signed_v = p[0];
  if (signed_v >= 0)
  {
    level = signed_v;
  }
  else
  {
    level = 0;
  }
  p[1] = level;
  if (word != 0)
  {
    flag = 1;
  }
  else
    if (flag)
  {
    flag = 0;
  }
  else
  {
    flag = 0;
  }
  if (flag & 0xFF)
  {
    note(word);
  }
  return level;
}
'''


def test_the_collapse_and_the_merge_are_one_child():
    collapsed = [text for _, text in identical_arm_collapse_repairs.variants(SOURCE, 'clamp')]
    merged = [text for family, text in integer_lifetime_repairs.variants(collapsed[0], 'clamp')
              if family == 'merge_integer_lifetimes']
    found = [text for family, text in c.variants(SOURCE, 'clamp') if family == c.FAMILY]
    assert found == merged[:len(found)] and found
    text = found[0]
    assert 'if (flag)' not in text
    assert text.count('signed_v = 0;') == 1 and 'flag' not in text.split('{', 1)[1]


def test_nothing_is_offered_without_an_identical_arm_guard():
    assert c.variants('s32 f(s32 a)\n{\n  s32 b;\n  b = a;\n  return b;\n}\n', 'f') == []

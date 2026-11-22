"""caller_save_slot_drop: m2c's caller-save round trip through a stack local dropped, and the copy it fed folded."""

from decomprepair import caller_save_slot_drop as m

SOURCE = """s32 g(s32);
void f(s32 *p, s32 n)
{
  s32 mask;
  s32 slot;
  s32 copy;
  s32 i;
  mask = *p & 0xFF;
  slot = mask;
  copy = mask;
  for (i = 0; i < n; i++)
  {
    if (copy & p[i])
    {
      slot = copy;
      copy = slot;
      g(i);
    }
  }
}
"""


def test_the_slot_and_its_round_trips_go():
    children = dict(m.variants(SOURCE, 'f'))
    text = children[m.FAMILY]
    assert 'slot' not in text
    assert 'copy = mask;' in text and 'if (copy & p[i])' in text


def test_the_combined_child_also_folds_the_copy():
    text = dict(m.variants(SOURCE, 'f'))[m.COMBINED]
    assert 'slot' not in text and 'copy' not in text
    assert 'mask = *p & 0xFF;' in text and 'if (mask & p[i])' in text


def test_a_slot_read_any_other_way_stays():
    used = SOURCE.replace('g(i);', 'g(slot);')
    assert m.variants(used, 'f') == []


def test_a_copy_assigned_again_is_not_folded():
    again = SOURCE.replace('g(i);', 'g(i);\n      copy = 3;')
    children = dict(m.variants(again, 'f'))
    assert m.FAMILY in children and m.COMBINED not in children

"""A scratch local written into a dead local of the same type (a voice picker's commit and last search loop, 360 -> 330 and 455 -> 60)."""
from decomprepair import registry
from decomprepair.dead_scratch_reuse import FAMILY, variants

SOURCE = """extern u8 links[];
extern u8 flags[];
s32 commit(s32 first, s32 best)
{
  s32 idx;
  s32 previous;
  s32 next;
  u32 other;
  idx = links[first];
  while (idx != 0xFF)
  {
    best += idx;
    idx = links[idx];
  }
  previous = flags[best];
  if (previous != 0xFF)
  {
    links[previous] = best;
  }
  next = flags[best + 1];
  if (next != 0xFF)
  {
    links[next] = best;
  }
  other = best;
  return other;
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'commit', '') if family == FAMILY]


def test_a_scratch_value_takes_the_variable_that_just_went_dead():
    texts = children()
    assert any('  idx = flags[best];\n  if (idx != 0xFF)\n  {\n    links[idx] = best;' in t for t in texts)
    one = [t for t in texts if '  previous = ' not in t and '  next = ' in t]
    assert one and '  s32 previous;\n' not in one[0]


def test_one_child_renames_every_scratch_that_can_take_the_same_variable():
    both = [t for t in children() if 'previous' not in t and 'next' not in t.replace('next = ', '')]
    assert both, children()
    text = both[0]
    assert '  idx = flags[best];' in text and '  idx = flags[best + 1];' in text
    assert 'links[idx] = best;' in text


def test_a_variable_read_later_without_a_write_is_not_taken():
    source = SOURCE.replace('  other = best;\n  return other;', '  other = best + idx;\n  return other;')
    assert not [t for t in children(source) if '  idx = flags[best];' in t]


def test_a_different_type_is_not_swapped_and_an_address_taken_is_left_alone():
    renamed = '  idx = flags[best];\n  if (idx != 0xFF)'
    assert [t for t in children() if renamed in t]
    assert not [t for t in children(SOURCE.replace('  s32 previous;', '  u16 previous;')) if renamed in t]
    taken = SOURCE.replace('  previous = flags[best];', '  previous = flags[best];\n  use(&previous);')
    assert not [t for t in children(taken) if renamed in t]


LOOPED = """extern u8 links[];
extern u8 flags[];
s32 walk(s32 first, s32 best)
{
  s32 idx;
  s32 previous;
  for (;;)
  {
%s    previous = flags[best];
    if (previous == 0) break;
%s  }
  idx = links[first];
  while (idx != 0xFF)
  {
    best += idx;
    idx = links[idx];
  }
  return best;
}
"""


def test_in_a_loop_the_variable_must_be_written_before_it_is_read_in_the_loop_body():
    def renames(source):
        return [t for family, t in variants(source, 'walk', '') if '    idx = flags[best];\n    if (idx == 0) break;' in t]

    assert not renames(LOOPED % ('    best += idx;\n', '    idx = links[best];\n'))
    assert renames(LOOPED % ('    idx = links[best];\n    best += idx;\n', ''))


def test_it_declares_itself_to_the_registry():
    assert any(FAMILY in repair.families for repair in registry.declared())

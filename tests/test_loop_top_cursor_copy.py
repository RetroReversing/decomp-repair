"""A loop's masked cursor copy at the top of the body (a chain walk in a voice picker, 1550 -> 1020)."""
from decomprepair import registry
from decomprepair.loop_top_cursor_copy import FAMILY, variants

SOURCE = """extern IndexLink links[];
extern u8 first[];
s32 pick(s32 limit, u16 cur)
{
  u32 pos;
  s32 best = -1;
  if ((cur & 0xFFFF) != 0xFFFF)
  {
    pos = cur & 0xFFFF;
    for (;;)
    {
      if ((limit >= pos) & (best == -1))
      {
        best = first[pos];
        cur = links[cur].index;
        pos = cur & 0xFFFF;
        if ((cur & 0xFFFF) != 0xFFFF)
        {
          continue;
        }
      }
      break;
    }
  }
  if ((cur & 0xFFFF) != 0xFFFF)
  {
    pos = cur & 0xFFFF;
    for (;;)
    {
      if (limit >= pos)
      {
        best += 1;
        cur = links[cur].index;
        pos = cur & 0xFFFF;
        if ((cur & 0xFFFF) != 0xFFFF)
        {
          continue;
        }
      }
      break;
    }
  }
  return best;
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'pick', '') if family == FAMILY]


def test_each_loop_gets_the_copy_at_its_top_and_one_child_does_both():
    first, second, both = children()
    assert first.count('pos = cur & 0xFFFF;') == 3
    assert 'for (;;)\n    {\npos = cur & 0xFFFF;\n      if ((limit >= pos) & (best == -1))' in first
    assert '    pos = cur & 0xFFFF;\n    for (;;)\n    {\n      if (limit >= pos)' in first
    assert second.index('pos = cur & 0xFFFF;') < second.index('for (;;)') < second.index('pos = cur & 0xFFFF;', second.index('for (;;)'))
    assert both.count('pos = cur & 0xFFFF;') == 2
    assert 'cur = links[cur].index;\n        if ((cur & 0xFFFF) != 0xFFFF)' in both


def test_a_read_after_the_loops_keeps_the_bottom_copy_unless_it_is_written_first():
    read = SOURCE.replace('  return best;', '  return best + pos;')
    assert not children(read)
    written = SOURCE.replace('  return best;', '  pos = 0;\n  return best + pos;')
    assert len(children(written)) == 3


def test_a_continue_before_the_bottom_copy_keeps_the_loop_as_it_is():
    source = SOURCE.replace('best = first[pos];', 'if (first[pos] == 0) continue;\n        best = first[pos];', 1)
    assert len(children(source)) == 1


def test_a_call_in_the_copy_or_a_changed_copy_is_not_moved():
    assert not children(SOURCE.replace('pos = cur & 0xFFFF;', 'pos = mask(cur);'))
    changed = SOURCE.replace('cur = links[cur].index;\n        pos = cur & 0xFFFF;', 'cur = links[cur].index;\n        pos = cur & 0xFFF;', 1)
    assert len(children(changed)) == 1


def test_it_declares_itself_to_the_registry():
    assert any(FAMILY in repair.families for repair in registry.declared())

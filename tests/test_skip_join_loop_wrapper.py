from decomprepair.skip_join_loop_wrapper import COLLAPSED, FAMILY, variants

HEAD = """typedef struct { u16 type; s16 state; } Slot;
extern Slot *gTable[];
extern s32 gTotal;
"""

LOOP = HEAD + """
void f(s16 skip)
{
  s16 i = 0;
  Slot *slot;
  do
  {
    if (((s16) i) != skip)
    {
      if (gTable)
      {
        slot = gTable[(s16) i];
      }
      else
      {
        slot = gTable[(s16) i];
      }
      if (slot != 0)
      {
        slot->state = 2;
      }
    }
    i++;
  }
  while (((s16) i) < gTotal);
}
"""


def test_the_skip_goes_to_a_label_heading_a_one_pass_loop_around_the_step():
    children = dict((family, text) for family, text in variants(LOOP, 'f'))
    plain = children[FAMILY]
    assert 'if (((s16) i) == skip) goto skip_join_1;' in plain
    assert 'do { skip_join_1: i++; } while (0);' in plain
    assert 'if (gTable)' in plain  # the guard stays in the plain child


def test_the_combined_child_collapses_the_identical_arm_guard_first():
    combined = dict(variants(LOOP, 'f'))[COLLAPSED]
    assert 'if (gTable)' not in combined and 'else' not in combined
    assert 'goto skip_join_1;' in combined and 'skip_join_1: i++;' in combined


def test_a_loop_whose_if_has_an_else_or_a_break_is_left_alone():
    with_else = LOOP.replace('slot->state = 2;\n      }\n    }', 'slot->state = 2;\n      }\n    }\n    else\n    {\n      i += 0;\n    }')
    assert variants(with_else, 'f') == []
    with_break = LOOP.replace('slot->state = 2;', 'slot->state = 2; break;')
    assert variants(with_break, 'f') == []


def test_a_loop_without_a_trailing_step_is_left_alone():
    text = LOOP.replace('    i++;\n', '    gTotal = 0;\n')
    assert variants(text, 'f') == []

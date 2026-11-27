"""A one-armed `if` before a returning tail, written as two paths (a timer update, SN64 gcc 2.8.1, 460 -> 0)."""
from decomprepair.guarded_arm_tail_return import FAMILY, variants

SOURCE = """void update(Ent *self)
{
  if (++timer >= limit)
  {
    if (phase != 0)
    {
      state = 1;
    }
    play(0x96);
    timer = 0;
    self->mode = 3;
    return;
  }
  other(self);
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'update') if family == FAMILY]


def test_the_guard_is_inverted_and_each_path_ends_with_the_tail():
    tail_first, arm_first = children()
    assert tail_first == SOURCE.replace(
        """    if (phase != 0)
    {
      state = 1;
    }
    play(0x96);
    timer = 0;
    self->mode = 3;
    return;
""", """    if (phase == 0)
    {
      play(0x96);
      timer = 0;
      self->mode = 3;
      return;
    }
    state = 1;
    play(0x96);
    timer = 0;
    self->mode = 3;
    return;
""")
    assert arm_first.count('play(0x96);') == 2
    assert 'if (phase != 0)\n    {\n      state = 1;\n      play(0x96);' in arm_first


def test_an_else_arm_is_left_alone():
    assert not children(SOURCE.replace('      state = 1;\n    }\n', '      state = 1;\n    }\n    else { state = 2; }\n'))


def test_a_tail_without_a_call_or_a_return_is_left_alone():
    assert not children(SOURCE.replace('    play(0x96);\n', ''))
    assert not children(SOURCE.replace('    return;\n', ''))


def test_an_arm_with_control_flow_is_left_alone():
    assert not children(SOURCE.replace('      state = 1;\n', '      return;\n'))

"""Two arms that each end in the same return, as an if/else and one return (a voice picker's table update, 4265 -> 2640)."""
from decomprepair import registry
from decomprepair.shared_return_tail import FAMILY, variants

SOURCE = """extern u8 music;
extern u8 sfx;
s32 count(s32 best, s32 flag)
{
  if (best != -1)
  {
    if (flag & 0xFF)
    {
      music += 1;
      return best;
    }
    sfx += 1;
    return best;
  }
  return -1;
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'count', '') if family == FAMILY]


def test_the_arms_become_if_else_and_one_return_follows():
    (child,) = children()
    assert '    if (flag & 0xFF)\n    {\n      music += 1;\n    }\n    else\n    {\n      sfx += 1;\n    }\n    return best;\n  }\n  return -1;\n}' in child
    assert child.count('return best;') == 1


def test_a_different_value_or_an_extra_return_in_an_arm_is_kept():
    assert not children(SOURCE.replace('    sfx += 1;\n    return best;', '    sfx += 1;\n    return flag;'))
    assert not children(SOURCE.replace('      music += 1;\n', '      if (music) return 0;\n      music += 1;\n'))


def test_a_statement_after_the_last_return_or_an_else_blocks_it():
    assert not children(SOURCE.replace('    sfx += 1;\n    return best;\n', '    sfx += 1;\n    return best;\n    music = 0;\n'))
    assert not children(SOURCE.replace('    sfx += 1;\n    return best;\n', '    sfx += 1;\n    return best;\n').replace('      return best;\n    }\n', '      return best;\n    }\n    else\n    {\n      sfx = 0;\n    }\n', 1))


def test_declarations_and_labels_stay_where_they_are():
    assert not children(SOURCE.replace('    sfx += 1;\n', '    s32 spare;\n    sfx += 1;\n'))
    assert not children(SOURCE.replace('    sfx += 1;\n', 'again:\n    sfx += 1;\n'))


def test_an_else_if_is_not_an_if_to_rewrite():
    source = SOURCE.replace('    if (flag & 0xFF)', '    if (flag == 0) { sfx = 0; }\n    else if (flag & 0xFF)')
    assert not children(source)


def test_it_declares_itself_to_the_registry():
    assert any(FAMILY in repair.families for repair in registry.declared())

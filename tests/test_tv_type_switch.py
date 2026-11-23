"""libultra's osTvType tested with an `if`, written as the game's switch over PAL, NTSC and MPAL."""
from decomprepair import registry
from decomprepair.tv_type_switch import FAMILY, variants

SOURCE = """void setup(void)
{
  u32 x;
  u32 y;

  x = 0;
  if (osTvType) {
    y = 0;
    x = y;
  } else {
    y = 0;
  }
  use(x, y);
}
"""

SWITCH = """  x = 0;
  y = 0;
  switch (osTvType) {
  case 0:
    break;
  case 1:
  case 2:
    x = y;
    break;
  }
  use(x, y);"""


def _children(source):
    return [child for family, child in variants(source, 'setup') if family == FAMILY]


def test_the_test_becomes_the_switch_with_the_shared_statement_before_it():
    assert SWITCH in _children(SOURCE)[0]


def test_the_arms_are_also_offered_whole():
    child = _children(SOURCE)[1]
    assert 'case 0:\n    y = 0;\n    break;' in child and 'case 2:\n    y = 0;\n    x = y;\n    break;' in child


def test_the_other_spellings_of_the_test_give_the_same_switch():
    zero = SOURCE.replace('if (osTvType) {\n    y = 0;\n    x = y;\n  } else {\n    y = 0;\n  }',
                          'if (osTvType == 0) {\n    y = 0;\n  } else {\n    y = 0;\n    x = y;\n  }')
    assert SWITCH in _children(zero)[0]
    assert SWITCH in _children(SOURCE.replace('if (osTvType)', 'if (osTvType != 0)'))[0]


def test_an_if_without_else_runs_its_arm_for_ntsc_and_mpal():
    source = SOURCE.replace('  } else {\n    y = 0;\n  }', '  }')
    assert 'case 0:\n    break;\n  case 1:\n  case 2:\n    y = 0;\n    x = y;\n    break;' in _children(source)[0]


def test_other_tests_and_arms_that_a_switch_would_change_are_left_alone():
    assert variants(SOURCE.replace('osTvType', 'gMode'), 'setup') == []
    assert variants(SOURCE.replace('    x = y;\n', '    x = y;\n    if (x) break;\n'), 'setup') == []
    assert variants(SOURCE.replace('if (osTvType)', 'if (osTvType > 1)'), 'setup') == []


def test_registry_declares_the_family():
    repair = registry.get('tv_type_switch')
    assert repair is not None and FAMILY in repair.families

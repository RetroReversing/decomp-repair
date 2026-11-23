"""A switch arm's dead exits, taken out: `if (x || y) { break; } else { break; }` and `do { break; } while (0);`."""
from decomprepair import registry
from decomprepair.switch_dead_exit_strip import FAMILY, variants

SOURCE = '''void step(void)
{
  switch (state)
  {
    case 1:
      if (a) { next = 1; } else { next = 2; }
      if (a || b)
      {
        break;
      }
      else
      {
        break;
      }
    case 2:
      if (a) { next = 3; } else { done = 0; }
      do
      {
        break;
      }
      while (0);
    case 3:
      next = 4;
      do { break; } while (0);
      other = 1;
      break;
  }
}
'''


def test_the_dead_test_becomes_the_break_and_the_scaffold_before_a_label_becomes_a_real_one():
    # a 417-instruction input handler: its fifth arm ran into its sixth through `do { break; } while (0);`
    (family, text), = variants(SOURCE, 'step')
    assert family == FAMILY
    assert 'if (a || b)' not in text and '      break;\n    case 2:' in text
    assert 'do\n      {\n        break;\n      }\n      while (0);' not in text and '      break;\n    case 3:' in text
    assert 'next = 4;\n      \n      other = 1;' in text  # not before a label: only taken out


def test_a_test_that_calls_something_or_arms_that_do_more_than_break_are_left_alone():
    assert variants(SOURCE.replace('if (a || b)', 'if (f(a))').replace('      do\n      {\n        break;\n      }\n      while (0);\n', '')
                    .replace('do { break; } while (0);', ''), 'step') == []
    assert variants('void step(void) { if (a) { break; } else { g(); } }', 'step') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'switch_dead_exit_strip' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'switch_dead_exit_strip':
            assert registry.problems(repair) == []

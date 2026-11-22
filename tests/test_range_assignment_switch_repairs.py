"""m2c's range-test compare tree over one variable, as a switch (a KMC gcc 2.7.2 menu function, 30 -> 0)."""
from decomprepair import range_assignment_switch_repairs as t

SOURCE = '''extern s32 *gState;
extern u16 gAction;
void f(void)
{
  s32 state;
  s32 var;
  state = *gState;
  if (state != 0x1A)
  {
    if (0x1B > ((s32) state))
    {
      var = 3;
      if (state != 0x19)
      {
        var = 1;
      }
    }
    else
    {
      if (state)
      {
        var = 1;
      }
      else
      {
        var = 1;
      }
      if (state == 0x1B)
      {
        var = 3;
      }
    }
  }
  else
  {
    var = 2;
  }
  gAction = var;
  g(gAction);
}
'''


def test_range_tree_becomes_the_switch():
    out = [text for _, text in t.variants(SOURCE, 'f')]
    grouped = out[0]
    assert 'switch (state)' in grouped and 'if (' not in grouped
    assert 'case 0x19:\n  case 0x1B:\n    var = 3;\n    break;\n' in grouped
    assert 'case 0x1A:' in grouped and 'default:' in grouped
    assert 'gAction = var;' in grouped
    assert any(text.count('var = 3;') == 2 for text in out[1:])


def test_a_local_set_once_to_a_constant_is_read():
    source = SOURCE.replace('  s32 var;\n', '  s32 var;\n  s32 three;\n').replace('  state = *gState;', '  three = 3;\n  state = *gState;')
    source = source.replace('var = 3;\n      if', 'var = three;\n      if')
    assert t.variants(source, 'f')


def test_a_range_that_differs_is_left_alone():
    source = SOURCE.replace('var = 1;\n      }\n    }\n  }', 'var = 4;\n      }\n    }\n  }')
    source = source.replace('      if (state != 0x19)\n      {\n        var = 1;', '      if (state != 0x19)\n      {\n        var = 4;')
    assert source != SOURCE
    assert t.variants(source, 'f') == [] or all('var = 4' in text for _, text in t.variants(source, 'f'))


def test_other_statements_and_unsigned_compares_are_left_alone():
    assert all('case 0x1A' not in text for _, text in t.variants(SOURCE.replace('var = 2;', 'h(); var = 2;'), 'f'))
    assert all('case 0x1A' not in text for _, text in t.variants(SOURCE.replace('state != 0x1A', 'state != 0x1AU'), 'f'))
    assert t.variants(SOURCE, 'missing') == []

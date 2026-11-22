"""The three steps of a KMC gcc 2.7.2 menu function (30 -> 0), offered as one child."""
from decomprepair import arm_switch_volatile_chain as t

SOURCE = '''extern s32 *gState;
extern u16 gAction;
extern s32 gGuard;
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
      var = 1;
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
  if (gGuard)
  {
    gAction = var;
  }
  else
  {
    gAction = var;
  }
  g(gAction);
}
'''


def test_the_three_steps_come_as_one_child():
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert out
    child = out[0]
    assert 'extern volatile u16 gAction;' in child
    assert 'switch (state)' in child and 'case 0x19:\n  case 0x1B:' in child
    assert 'if (gGuard)' not in child and child.count('gAction = var;') == 1


def test_no_chain_without_all_three_steps():
    assert t.variants(SOURCE.replace('  if (gGuard)\n  {\n    gAction = var;\n  }\n  else\n  {\n    gAction = var;\n  }\n', '  gAction = var;\n'), 'f') == []
    assert t.variants(SOURCE.replace('g(gAction);', ''), 'f') == []

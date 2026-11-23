"""A call after a switch whose arguments the arms assigned, written as one call at the end of each arm."""
from decomprepair import registry
from decomprepair.switch_arm_tail_calls import FAMILY, variants

SOURCE = '''void run(s32 k, s32 idx)
{
  s32 t0;
  s32 t1;
  void *a;
  s32 b;
  switch (k)
  {
    case 0:
      t0 = idx & 0xFF;
      a = &D_A;
      b = t0;
      first(&D_B, t0);
      break;

    case 1:
      a = &D_C;
      b = idx;
      first(a, 1);
      a = &D_D;
      break;

    default:
      t1 = idx & 0xFF;
      a = &D_E;
      b = t1;
      first(&D_F, t1);
      break;
  }
  second(a, b, 7);
}
'''


def test_the_shared_call_is_copied_to_the_end_of_each_arm_with_the_arms_values():
    # eight arms of a 417-instruction input handler: the arguments' multiple-set pseudos and the address loads hoisted
    # above the arms' first call were the difference (3145 -> 1655 with the byte parameter, 905 with the rest)
    tailed, inlined = (text for _, text in variants(SOURCE, 'run'))
    assert variants(SOURCE, 'run')[0][0] == FAMILY
    assert '  second(a, b, 7);\n' not in tailed
    assert 'second(&D_A, t0, 7);\n      break;' in tailed.replace('\n      second', '\n      second')
    assert 'second(&D_D, idx, 7);' in tailed       # the arm's last value of `a`, the earlier value of `b` kept as is
    assert 'second(&D_E, t1, 7);' in tailed
    assert 'first(&D_C, 1);' in tailed and 'a = &D_C;' not in tailed  # the arm's own read sees the value assigned before it
    assert 'a = &D_A;' not in tailed and 'b = t0;' not in tailed     # nothing reads them any more
    assert 'second(&D_A, (idx & 0xFF), 7);' in inlined and 't0' not in inlined.split('switch', 1)[1]
    assert 'second(&D_E, (idx & 0xFF), 7);' in inlined


def test_a_switch_the_call_cannot_be_moved_into_is_left_alone():
    assert variants(SOURCE.replace('      first(&D_F, t1);\n      break;', '      first(&D_F, t1);\n      return;'), 'run') == []
    assert variants(SOURCE.replace('  second(a, b, 7);\n', '  c = 1;\n  second(a, b, 7);\n'), 'run') == []
    assert variants(SOURCE.replace('second(a, b, 7)', 'second(7)'), 'run') == []
    assert variants(SOURCE.replace('      first(&D_B, t0);\n      break;', '      if (t0) break;\n      first(&D_B, t0);\n      break;'), 'run') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'switch_arm_tail_calls' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'switch_arm_tail_calls':
            assert registry.problems(repair) == []

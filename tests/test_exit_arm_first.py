"""A two-arm test whose short arm only stores a constant, written with that arm first."""
from decomprepair import registry
from decomprepair.exit_arm_first import FAMILY, variants

SOURCE = '''void step(void)
{
  switch (state)
  {
    case 4:
      if (a == 0) { next = mask_a & 0xA; } else { done = 0; }
      break;
    case 5:
      if (b == 0) { next = mask_b & 0xB; } else { done = 0; }
      break;
  }
}
'''


def test_the_exit_arm_comes_first_in_each_test_and_in_all_of_them_at_once():
    # the four closing arms of a state machine in a 417-instruction input handler, 1980 -> 840 with the dead tests gone
    found = variants(SOURCE, 'step')
    assert [family for family, _ in found] == [FAMILY] * 3
    first, second, both = (text for _, text in found)
    assert 'if (a != 0) { done = 0; } else { next = mask_a & 0xA; }' in first and 'if (b == 0)' in first
    assert 'if (a == 0)' in second and 'if (b != 0) { done = 0; } else { next = mask_b & 0xB; }' in second
    assert 'if (a != 0)' in both and 'if (b != 0)' in both and '== 0' not in both


def test_arms_that_are_not_one_store_each_or_a_test_that_is_not_one_comparison_are_left_alone():
    assert variants(SOURCE.replace('done = 0;', 'done = f();'), 'step') == []
    (_, only), = variants(SOURCE.replace('next = mask_a & 0xA;', 'next = 3;'), 'step')   # a constant in both arms: the second test only
    assert 'if (a == 0) { next = 3; }' in only and 'if (b != 0) { done = 0; }' in only
    (_, only), = variants(SOURCE.replace('{ next = mask_a & 0xA; }', '{ next = 1; g(); }'), 'step')
    assert 'g();' in only and 'if (b != 0) { done = 0; }' in only
    (_, only), = variants(SOURCE.replace('a == 0', 'a == 0 && c'), 'step')
    assert 'a == 0 && c' in only and 'if (b != 0)' in only


def test_the_module_declares_itself_to_the_registry():
    assert 'exit_arm_first' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'exit_arm_first':
            assert registry.problems(repair) == []

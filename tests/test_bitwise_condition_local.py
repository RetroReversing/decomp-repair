from decomprepair import registry
from decomprepair.bitwise_condition_local import FAMILY_LOCAL, FAMILY_SWAP, REPAIR, variants

SOURCE = """void tick(void *arg0)
{
  s32 var_a1;
  u16 temp_v0;
  temp_v0 = (*((u16 *) (((char *) arg0) + 0x14))) + 1;
  *((u16 *) (((char *) arg0) + 0x14)) = temp_v0;
  if ((((s16) temp_v0) < 0xA0) & (D_800FFC70 != 2))
  {
    *((u16 *) (((char *) arg0) + 0x14)) = 0xA0U;
    var_a1 = 0xA0;
  }
  if (var_a1 == 0x1E0)
  {
    reset();
  }
}
"""


def kids(source=SOURCE, family=None):
    return [c for f, c in variants(source, 'tick') if family in (None, f)]


def test_the_narrowed_value_is_set_in_the_phi_local_and_the_flag_is_tested_first():
    child = kids(family=FAMILY_LOCAL)[0]
    assert 'var_a1 = (s16) temp_v0;\n  if ((D_800FFC70 != 2) & (var_a1 < 0xA0))' in child
    assert 's32 cond_' not in child, 'the function already has the phi local'


def test_the_original_order_with_the_local_is_offered_too():
    assert any('if ((var_a1 < 0xA0) & (D_800FFC70 != 2))' in c for c in kids(family=FAMILY_LOCAL))


def test_the_swap_alone_is_a_child():
    assert 'if ((D_800FFC70 != 2) & (((s16) temp_v0) < 0xA0))' in kids(family=FAMILY_SWAP)[0]


def test_a_new_local_is_declared_when_the_body_assigns_none():
    source = SOURCE.replace('    var_a1 = 0xA0;\n', '    reset();\n').replace('  if (var_a1 == 0x1E0)', '  if (arg0)')
    child = kids(source, FAMILY_LOCAL)[0]
    assert 's32 cond_temp_v0;' in child and 'cond_temp_v0 = (s16) temp_v0;' in child


def test_a_short_circuit_or_a_call_in_the_condition_is_left_alone():
    assert not kids(SOURCE.replace('& (D_800FFC70', '&& (D_800FFC70'))
    assert not kids(SOURCE.replace('(D_800FFC70 != 2)', '(check() != 2)'))


def test_the_module_declares_itself():
    assert REPAIR['families'] == (FAMILY_LOCAL, FAMILY_SWAP)
    assert registry.problems(registry.get('bitwise_condition_local')) == []

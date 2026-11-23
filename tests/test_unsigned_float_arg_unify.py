"""An unsigned local converted through a signed double cast at some uses, written (f32)v at every use."""
from decomprepair import registry
from decomprepair.unsigned_float_arg_unify import FAMILY, variants

SOURCE = """void setup(void)
{
  u32 x;
  u32 y;

  x = 0;
  y = 0;
  if (gSlot == NULL) {
    if (gTable) {
      make(4);
    } else {
      make(4);
    }
  }
  draw(gSlot, (f32)(f64)x, (f32)(f64)(s32)y);
  draw(gOther, (f32)(f64)x, (f32)(f64)y);
}
"""


def _children(source):
    return [child for family, child in variants(source, 'setup') if family == FAMILY]


def test_every_cast_of_the_local_becomes_the_plain_conversion_and_the_guard_goes():
    child = _children(SOURCE)[0]
    assert child.count('(f32)y') == 2 and '(f64)(s32)y' not in child and '(f64)y' not in child
    assert 'if (gTable)' not in child and child.count('make(4);') == 1
    assert '(f32)(f64)x' in child  # x was never read through the signed cast


def test_the_casts_alone_are_a_child_too():
    assert any('if (gTable)' in child and child.count('(f32)y') == 2 for child in _children(SOURCE))


def test_a_signed_local_or_no_signed_cast_is_left_alone():
    assert variants(SOURCE.replace('  u32 y;', '  s32 y;'), 'setup') == []
    assert variants(SOURCE.replace('(f32)(f64)(s32)y', '(f32)(f64)y'), 'setup') == []


def test_registry_declares_the_family():
    repair = registry.get('unsigned_float_arg_unify')
    assert repair is not None and FAMILY in repair.families

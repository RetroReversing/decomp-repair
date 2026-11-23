"""An early return guard written as the guard block around the rest, with the same return after it (a voice picker, 5240 -> 4855)."""
from decomprepair import registry
from decomprepair.early_return_guard_block import FAMILY, _negate, variants

SOURCE = """extern u8 disabled;
extern u8 table[];
s32 pick(s32 a, s32 best)
{
  if (disabled != 0)
  {
    return -1;
  }
  if (a > 3)
  {
    table[0] = a;
    return a;
  }
  if (best == -1)
  {
    return -1;
  }
  table[1] = best;
  return best;
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'pick', '') if family == FAMILY]


def test_the_leading_guard_wraps_the_rest_and_the_return_follows_the_block():
    first = children()[0]
    assert first.startswith('extern u8 disabled;')
    assert '  if (disabled == 0)\n  {\n  if (a > 3)' in first
    assert first.rstrip().endswith('  return best;\n  }\n  return -1;\n}')
    assert first.count('return -1;') == 2  # the inner guard keeps its own return


def test_a_guard_inside_a_block_followed_by_the_same_return_loses_its_own():
    nested = """s32 pick(s32 a, s32 best)
{
  if (a == 0)
  {
    if (best == -1)
    {
      return -1;
    }
    table[1] = best;
    return best;
  }
  return -1;
}
"""
    (child,) = children(nested)
    assert '    if (best != -1)\n    {\n    table[1] = best;\n    return best;\n    }\n  }\n  return -1;\n}' in child


def test_a_rest_that_can_fall_out_or_a_different_value_is_not_wrapped():
    assert not [t for t in children(SOURCE.replace('  table[1] = best;\n  return best;', '  table[1] = best;'))
                if t.startswith('extern u8 disabled;') and '(best != -1)' in t]
    nested = SOURCE.replace('  if (disabled != 0)\n  {\n    return -1;\n  }\n', '')
    assert not [t for t in children(nested.replace('(best == -1)\n  {\n    return -1;', '(best == -1)\n  {\n    return -2;')) if 'return -2' not in t]


def test_negation_inverts_one_comparison_and_wraps_anything_else():
    assert _negate('x != 0') == 'x == 0'
    assert _negate('x >= y') == 'x < y'
    assert _negate('!ready') == 'ready'
    assert _negate('ready') == '!ready'
    assert _negate('a && b') == '!(a && b)'
    assert _negate('(a & 1) == 0') == '(a & 1) != 0'
    assert _negate('f(x) < 2') == 'f(x) >= 2'


def test_an_else_arm_blocks_the_guard():
    source = SOURCE.replace('    return -1;\n  }\n  if (a > 3)', '    return -1;\n  }\n  else\n  {\n    a = 0;\n  }\n  if (a > 3)', 1)
    assert not [t for t in children(source) if 'if (disabled == 0)' in t]


def test_it_declares_itself_to_the_registry():
    assert any(FAMILY in repair.families for repair in registry.declared())

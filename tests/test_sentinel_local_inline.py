"""A constant local that only feeds `!=` compares written as its literal again (a collision sweep, 1467 -> 487)."""
from decomprepair.sentinel_local_inline import FAMILY, variants

SOURCE = """s32 sweep(Obj *o)
{
  s32 sentinel = -1;
  s32 hit;

  hit = -1;
  do
  {
    hit = test(o);
    o = o->next;
  }
  while (o != NULL);
  if (hit != sentinel)
  {
    return hit;
  }
  return 0;
}
"""


def test_the_compare_reads_the_literal_and_the_local_is_gone():
    found = variants(SOURCE, 'sweep')
    assert [family for family, _ in found] == [FAMILY]
    text = found[0][1]
    assert 'sentinel' not in text
    assert 'if (hit != (-1))' in text


def test_a_local_assigned_later_or_read_otherwise_is_kept():
    assert variants(SOURCE.replace('    o = o->next;', '    sentinel = hit;\n    o = o->next;'), 'sweep') == []
    assert variants(SOURCE.replace('return hit;', 'return sentinel;'), 'sweep') == []


def test_a_local_set_once_after_its_declaration_is_inlined_too():
    source = SOURCE.replace('  s32 sentinel = -1;\n', '  s32 sentinel;\n').replace('  hit = -1;\n', '  sentinel = -1;\n  hit = -1;\n')
    found = variants(source, 'sweep')
    assert found and 'sentinel' not in found[0][1] and 'if (hit != (-1))' in found[0][1]

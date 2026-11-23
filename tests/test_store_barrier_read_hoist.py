"""An address-taken local read before the pointer store in front of it (a player update, 550 -> 320)."""
from decomprepair.store_barrier_read_hoist import FAMILY, REPAIR, variants

SOURCE = """void tail(Obj *obj)
{
  struct
  {
    s32 pad;
    s32 flags;
    s32 count;
  } locals;
  void *rec;
  locals.count = 0;
  query(obj, &locals.flags, &locals.count);
  rec = obj->rec;
  rec->mask = rec->mask & 0xFFFB;
  if ((locals.count != 0) && (locals.flags & 2))
  {
    rec->mask = rec->mask | 4;
  }
}
"""


def children(source):
    return [text for family, text in variants(source, 'tail') if family == FAMILY]


def test_the_read_moves_ahead_of_the_store_and_the_condition_uses_the_copy():
    found = children(SOURCE)
    assert len(found) == 1
    child = found[0]
    assert '  s32 count_early;\n' in child
    assert child.index('count_early = locals.count;') < child.index('rec->mask = rec->mask & 0xFFFB;')
    assert 'if ((count_early != 0) && (locals.flags & 2))' in child


def test_a_local_whose_address_is_never_taken_is_left_alone():
    assert children(SOURCE.replace('&locals.count', '&locals.pad')) == []


def test_a_store_to_a_plain_variable_or_a_condition_without_the_member_first_is_left_alone():
    assert children(SOURCE.replace('rec->mask = rec->mask & 0xFFFB;', 'rec = other;')) == []
    assert children(SOURCE.replace('(locals.count != 0) && (locals.flags & 2)', 'gMode && (locals.count != 0)')) == []


def test_a_member_of_an_undeclared_struct_is_left_alone():
    assert children(SOURCE.replace('  struct\n  {\n    s32 pad;\n    s32 flags;\n    s32 count;\n  } locals;\n', '')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and FAMILY in REPAIR['families']

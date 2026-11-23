"""A snapshot of an address-taken local given back, with a copy at the top of the block that uses it (1420 -> 1270)."""
from decomprepair.address_taken_snapshot_split import FAMILY, REPAIR, variants

SOURCE = """void run(Obj *obj)
{
  struct
  {
    s32 flags;
    void *out;
  } locals;
  void *snap;
  s32 mode;
  query(obj, &locals.flags, &locals.out);
  snap = locals.out;
  if ((snap != NULL) && (locals.flags & 1))
  {
    mode = obj->mode;
    if ((mode != 1) && (measure(obj, snap->a) > 2.0f))
    {
      obj->x = snap->x + snap->z;
      obj->y = snap->y - snap->z;
      settle(obj);
    }
  }
}
"""


def children(source):
    return [text for family, text in variants(source, 'run') if family == FAMILY]


def test_the_condition_reads_the_slot_and_the_block_copies_it_once():
    found = children(SOURCE)
    assert len(found) == 1
    child = found[0]
    assert 'snap = locals.out;' not in child
    assert '  void *snap_body;\n' in child
    assert 'if ((locals.out != NULL) && (locals.flags & 1))' in child
    assert 'measure(obj, locals.out->a)' in child
    assert '{\n      snap_body = locals.out;\n      obj->x = snap_body->x + snap_body->z;' in child
    assert 'snap_body->y - snap_body->z' in child


def test_a_local_whose_address_is_not_taken_or_used_after_the_if_is_left_alone():
    assert children(SOURCE.replace('&locals.out', '&locals.flags')) == []
    assert children(SOURCE.replace('      settle(obj);\n    }\n  }\n}', '      settle(obj);\n    }\n  }\n  finish(snap);\n}')) == []


def test_a_variable_assigned_twice_is_left_alone():
    assert children(SOURCE.replace('  query(obj', '  snap = 0;\n  query(obj')) == []


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and FAMILY in REPAIR['families']

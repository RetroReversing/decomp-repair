"""A record slot's stores through a pointer to the slot, and the tested member held for its update."""
from decomprepair.record_slot_stores import FAMILY, HELD, variants

PLAIN = '''extern Rec table[];
void f(u16 i)
{
  if (table[i].count < 6)
  {
    table[i].count++;
    table[i].total++;
  }
  else if ((u32) (table[i].count - 6) < 6)
  {
    table[i].count++;
    table[i].total--;
  }
}
'''


def _squash(text):
    return ' '.join(text.split())


def _children(source, family):
    return [_squash(t) for f, t in variants(source, 'f') if f == family]


def test_every_run_is_stored_through_a_slot_pointer_with_indexed_reads():
    both = _children(PLAIN, FAMILY)[0]
    assert both.count('Rec *__repair_slot = &table[i];') == 2
    assert '__repair_slot->count = table[i].count + 1; __repair_slot->total = table[i].total - 1; }' in both


def test_the_tested_member_is_held_and_the_update_starts_from_it():
    held = _children(PLAIN, HELD)
    assert any('else { s32 __repair_held = table[i].count; if ((u32) (__repair_held - 6) < 6) { '
               'table[i].count = __repair_held + 1; table[i].total--; } }' in t for t in held), held


def test_one_write_alone_is_left():
    source = PLAIN.replace('table[i].total++;', '').replace('table[i].total--;', '')
    assert not _children(source, FAMILY)


def test_a_run_of_numbers_stays_indexed_in_the_first_child():
    source = PLAIN[:-2] + '  else\n  {\n    table[i].count = 0;\n    table[i].total = 0;\n  }\n}\n'
    first = _children(source, FAMILY)[0]
    assert first.count('__repair_slot = &table[i];') == 2
    assert 'table[i].count = 0; table[i].total = 0;' in first

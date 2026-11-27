"""A hoist that had turned a store into a local: the store comes back; a written field is never hoisted again."""
from decomprepair import field_load_hoist_repairs, lost_store_restore

DAMAGED = """void step(void *arg0)
{
  void * __repair_hoisted;
  void *made;
  __repair_hoisted = M2C_FIELD(arg0, void **, 0x48);
  if (ready != 1) {
    made = make();
    __repair_hoisted = made;
    use(made);
  }
}
"""

STORE = """void step(void *arg0)
{
  void *made;
  if (ready != 1) {
    made = make();
    M2C_FIELD(arg0, void **, 0x48) = made;
    use(made);
  }
}
"""


def test_the_store_comes_back():
    [(family, text)] = lost_store_restore.variants(DAMAGED, 'step')
    assert family == lost_store_restore.FAMILY
    assert 'M2C_FIELD(arg0, void **, 0x48) = made;' in text
    assert '__repair_hoisted' not in text


def test_a_read_local_is_left():
    assert lost_store_restore.variants(DAMAGED.replace('use(made);', 'use(__repair_hoisted);'), 'step') == []


def test_a_written_field_is_not_hoisted():
    assert field_load_hoist_repairs.variants(STORE, 'step') == []
    for write in ('M2C_FIELD(arg0, void **, 0x48) += 4;', 'M2C_FIELD(arg0, void **, 0x48)++;',
                  'use(&M2C_FIELD(arg0, void **, 0x48));'):
        assert field_load_hoist_repairs.variants(STORE.replace('M2C_FIELD(arg0, void **, 0x48) = made;', write), 'step') == []


def test_a_read_is_still_hoisted():
    source = STORE.replace('M2C_FIELD(arg0, void **, 0x48) = made;', 'use(M2C_FIELD(arg0, void **, 0x48));')
    [(_, text)] = field_load_hoist_repairs.variants(source, 'step')
    assert '__repair_hoisted = M2C_FIELD(arg0, void **, 0x48);' in text

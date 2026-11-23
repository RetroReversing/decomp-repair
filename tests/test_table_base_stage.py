"""table_base_stage: a table slot's address written with the index and the base staged before it.

Synthetic shape of a 795-instruction KMC object spawner (120 -> 60 -> 0, two slot lookups): the table's `la` sat after both
halves of the index's shifts; staged, it sits between them as in the game's code."""
from decomprepair import table_base_stage as s

SOURCE = '''extern void *sTable[];
void spawn(s16 id, void *obj) {
  void **slot;
  void **other;
  put(obj);
  slot = &sTable[(s16) id];
  set(*slot, 1);
  other = &sTable[(s16) id];
  clear(*other);
}
'''


def _texts(source=SOURCE, header=''):
    return [text for family, text in s.variants(source, 'spawn', header=header) if family == s.FAMILY]


def test_each_lookup_alone_and_both_together():
    texts = _texts()
    assert len(texts) == 3
    both = [t for t in texts if 'slot1_index' in t and 'slot2_index' in t]
    assert len(both) == 1
    text = both[0]
    assert '  slot1_index = (s16) id;\n  slot1_table = sTable;\n  slot = &slot1_table[slot1_index];' in text
    assert '  s32 slot1_index;\n' in text and '  void **slot1_table;\n' in text


def test_the_array_may_come_from_the_header():
    source = SOURCE.replace('extern void *sTable[];\n', '')
    assert len(_texts(source, header='extern void *sTable[];\n')) == 3


def test_a_wide_index_or_a_plain_pointer_is_left_alone():
    assert _texts(SOURCE.replace('(s16) id', 'id')) == []
    assert _texts(SOURCE.replace('extern void *sTable[];', 'extern void *sTable;')) == []
    assert _texts(SOURCE.replace('  void **slot;\n  void **other;\n', '  s32 slot;\n  s32 other;\n')) == []

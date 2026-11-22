"""The record search with a carried id, as direct reads."""
from decomprepair import loaded_search_fold as s

SOURCE = '''s32 f(s32 map)
{
    s32 offset = 0;
    s32 key = (s16) map;
    s32 sentinel = -1;
    s16 *entry = (s16 *) table;
    s32 id;
    map = 0;
    id = *entry;
    do
    {
      entry += 4;
      if (key == id)
      {
        offset = *((s32 *) (0x8011EB64 + map));
        goto found;
      }
      id = *entry;
      map += 8;
    }
    while (id != sentinel);
    found:
    return offset;
}
'''


def test_the_loop_reads_the_entry_where_it_compares():
    out = [text for _, text in s.variants(SOURCE, 'f')]
    assert len(out) == 2
    direct = out[0]
    assert 'if (*entry == key)' in direct and 'while (*entry != sentinel);' in direct
    assert 'id = *entry' not in direct and 'entry += 4;' in direct
    assert direct.index('goto found;') < direct.index('entry += 4;') < direct.index('map += 8;')
    assert 'if (key == *entry)' in out[1]


def test_a_hit_that_names_the_entry_is_left_alone():
    source = SOURCE.replace('offset = *((s32 *) (0x8011EB64 + map));', 'offset = *entry;')
    assert s.variants(source, 'f') == []

"""A loop over the local that was stored to a global, reading the global into a loop-scoped local instead."""
from decomprepair import loop_global_base as r

SOURCE = '''typedef struct { s16 slot; u16 flags; } Entry;
extern Entry *G;
inline static Entry *as_entry(u8 *arg0)
{
  return (Entry *) arg0;
}

inline static int mask(u16 arg0, int arg1)
{
  return arg0 & arg1;
}

void f(u16 count, Entry *table)
{
  short i;
  Entry *entries;
  Entry *entry;
  s32 flags;
  entries = table;
  G = entries;
  for (i = 0; ((u16) i) < count; ++i)
  {
    if (entries == NULL)
    {
      break;
    }
    entry = (Entry *) ((((u16) i) * 4) + ((u8 *) entries));
    flags = mask(entry->flags, 0xFDF0);
    entry->flags = flags;
  }
}
'''


def test_the_loop_reads_the_global_into_a_local_and_tests_it_first():
    # A map-table setup (KMC gcc 2.7.2): m2c's loop over `entries`, scored 85; the original read the global in the
    # loop, as its second loop did. The step alone scored the same (85) and is what the later steps (a member read of
    # one field, a reorder of the header's statements) need: 85 -> 50 -> 0.
    found = [text for _, text in r.variants(SOURCE, 'f')]
    staged, helped = found
    assert '    Entry *base = G;\n    if (base == NULL)' in staged
    assert 'entry = (Entry *) ((((u16) i) * 4) + ((u8 *) base));' in staged
    assert 'entries' not in staged.split('for (')[1]
    assert 'entry = as_entry((((u16) i) * 4) + ((u8 *) base));' in helped
    assert staged.startswith(SOURCE.split('void f(')[0]) and 'G = entries;' in staged


def test_the_cast_helper_is_only_used_when_the_source_has_one():
    plain = SOURCE.replace('inline static Entry *as_entry(u8 *arg0)\n{\n  return (Entry *) arg0;\n}\n', '')
    assert len(r.variants(plain, 'f')) == 1


def test_a_taken_name_is_not_reused():
    taken = SOURCE.replace('  s32 flags;', '  s32 flags;\n  Entry *base;')
    assert all('Entry *base_ = G;' in text for _, text in r.variants(taken, 'f'))


def test_left_alone_when_the_loop_could_change_the_pointer_or_the_global():
    assert r.variants(SOURCE.replace('    entry->flags = flags;', '    entry->flags = flags;\n    G = 0;'), 'f') == []
    assert r.variants(SOURCE.replace('    entry->flags = flags;', '    entry->flags = flags;\n    entries++;'), 'f') == []
    assert r.variants(SOURCE.replace('    entry->flags = flags;', '    entry->flags = flags;\n    g(entry);'), 'f') == []
    # no store of the local to a global, or the loop comes before it
    assert r.variants(SOURCE.replace('  G = entries;\n', ''), 'f') == []
    assert r.variants(SOURCE.replace('  G = entries;\n  for', '  for').replace('    entry->flags = flags;\n  }\n',
                                                                          '    entry->flags = flags;\n  }\n  G = entries;\n'), 'f') == []
    assert r.variants('void f(void) { g(); }\n', 'f') == []

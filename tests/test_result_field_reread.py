"""result_field_reread: a call's result stored in a field and passed on, written through the field.

Synthetic shape of a 795-instruction KMC object spawner (4030 -> 3660, two spans): a marker pointer held in a saved register
for the span, where the game's code had it only in `$v0` and read the field again."""
from decomprepair import result_field_reread as s

SOURCE = '''void spawn(void *rec, s32 slot) {
  void *m;
  m = mark(slot);
  rec->first = m;
  init(m, 0x2B, 0x1B);
  m = mark(slot + 1);
  *(void **) ((char *) rec + 0x40C) = m;
  init(m, 0x30, 0x1B);
  done(rec);
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'spawn') if family == s.FAMILY]


def test_each_span_alone_and_both_together():
    texts = _texts()
    assert len(texts) == 3
    both = [t for t in texts if 'm = mark' not in t]
    assert len(both) == 1
    assert 'rec->first = mark(slot);\n  init(rec->first, 0x2B, 0x1B);' in both[0]
    assert '*(void **) ((char *) rec + 0x40C) = mark(slot + 1);' in both[0]
    assert 'init(*(void **) ((char *) rec + 0x40C), 0x30, 0x1B);' in both[0]


def test_a_later_read_of_the_local_stops_that_span():
    source = SOURCE.replace('  done(rec);', '  done(m);')
    texts = _texts(source)
    assert all('mark(slot + 1);\n  init(m' in t or '*(void **) ((char *) rec + 0x40C) = m;' in t for t in texts)
    assert len(texts) == 1 and 'rec->first = mark(slot);' in texts[0]


def test_a_local_assigned_later_is_still_rewritten():
    source = SOURCE.replace('  done(rec);', '  m = 0;\n  done(rec);')
    assert len(_texts(source)) == 3


def test_a_side_effect_in_the_store_target_is_left_alone():
    source = SOURCE.replace('rec->first = m;', 'rec->list[n++] = m;')
    texts = _texts(source)
    assert all('rec->list[n++] = m;' in t or 'n++' not in t for t in texts)
    assert len(texts) == 1

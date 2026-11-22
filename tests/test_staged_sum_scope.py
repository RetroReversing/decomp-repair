from decomprepair.staged_sum_scope import GUARDED, STAGED, variants

SOURCE = """s32 f(u32 arg0, s32 n, s32 k)
{
  u8 vol;
  s32 sum;
  s32 base;
  s32 clamped;
  s32 cur;
  s32 next;
  void *p;
  p = table;
  base = n + (*((s8 *) (((char *) p) + 4)));
  vol = (k * (*((u8 *) (((char *) p) + 5))))/127;
  sum = (*((s16 *) (((char *) p) + 6))); sum = ((arg0 >> 8) & 0xFF) + sum;
  if (sum < 0x100)
  {
    clamped = sum;
  }
  else
  {
    clamped = 0xFF;
  }
  next = play(clamped, vol, base);
  if (next != -1)
  {
    *((s32 *) (gTable + ((cur & 0xFF) * 0x1A0))) = next;
    cur = next;
  }
  return cur;
}
"""


def _found(family, source=SOURCE):
    return [text for fam, text in variants(source, 'f') if fam == family]


def test_the_quotient_and_the_staged_sum_share_a_scope_that_ends_with_the_test():
    found = _found(STAGED)
    assert found
    out = next(t for t in found if 'factor' in t and 'base = n' in t and 'do {  base' not in t.replace('\n', ' '))
    flat = ' '.join(out.split())
    assert 'factor = (*((u8 *) (((char *) p) + 5))); do { vol = (k * factor)/127;' in flat
    assert 'sum = ((arg0 >> 8) & 0xFF); sum += (*((s16 *) (((char *) p) + 6))); in_range = sum < 0x100; } while (0); if (in_range)' in flat
    assert 'u8 factor;' in flat and 's32 in_range;' in flat


def test_a_child_also_wraps_the_nearest_earlier_load_and_add():
    flat = [' '.join(t.split()) for t in _found(STAGED)]
    assert any('do { base = n + (*((s8 *) (((char *) p) + 4))); } while (0);' in t and 'if (in_range)' in t for t in flat)


def test_the_factor_load_can_stay_in_the_quotient():
    flat = [' '.join(t.split()) for t in _found(STAGED)]
    assert any('do { vol = (k * (*((u8 *) (((char *) p) + 5))))/127;' in t for t in flat)


def test_nothing_staged_without_the_split_sum_before_the_test():
    source = SOURCE.replace('sum = (*((s16 *) (((char *) p) + 6))); sum = ((arg0 >> 8) & 0xFF) + sum;',
                            'sum = ((arg0 >> 8) & 0xFF) + (*((s16 *) (((char *) p) + 6)));')
    assert not _found(STAGED, source)


def test_a_guarded_block_of_stores_and_copies_is_wrapped():
    flat = [' '.join(t.split()) for t in _found(GUARDED)]
    assert any('if (next != -1) { do {' in t and 'cur = next; } while (0); }' in t for t in flat)


def test_a_guarded_block_with_a_call_or_a_single_statement_is_left_alone():
    flat = [' '.join(t.split()) for t in _found(GUARDED)]
    assert not any('if (sum < 0x100) { do {' in t for t in flat)
    source = SOURCE.replace('    cur = next;\n', '    cur = play(next, 0, 0);\n')
    assert not _found(GUARDED, source)

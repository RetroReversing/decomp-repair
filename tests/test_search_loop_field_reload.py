"""A table search spelt as the counted `for` that re-reads the table field, and the two moves that go with it."""
from decomprepair import accumulation_run_scope, frame_padding_repairs, search_loop_field_reload

SOURCE = '''typedef struct Rec { u8 *pairs; u8 count; } Rec;
typedef struct Obj { u8 pad0[8]; u8 *glyphs; u8 *table; s8 extra; } Obj;
u32 measure(u8 *text, s32 n, Obj *obj)
{
  u32 width;
  u32 total;
  u32 key;
  s32 idx;
  u32 k;
  u8 *p;
  u8 ch;
  s32 off;
  u8 *table;
  Rec *rec;
  s32 adv;
  volatile u32 pad[4];
  width = 0;
  total = 0;
  ch = *text;
  key = ch;
  idx = ch - 0x21;
  table = obj->table;
  if (table != 0)
  {
    if (n || idx)
    {
      off = idx * 8;
    }
    else
    {
      off = idx * 8;
    }
    if (((Rec *) (table - (-(2 * (idx * 4)))))->count != 0)
    {
      k = 0;
      for (;;)
      {
        if (ch)
        {
          rec = (Rec *) ((idx * 8) + table);
          p = (u8 *) ((*((u8 * volatile *) (&rec->pairs))) + (k * 2));
          k++;
        }
        else
        {
          rec = (Rec *) ((idx * 8) + table);
          p = (u8 *) ((*((u8 * volatile *) (&rec->pairs))) + (k * 2));
          k++;
        }
        if (p[0] == key)
        {
          width -= (s8) p[1];
        }
        else
          if (k < rec->count)
        {
          continue;
        }
        break;
      }
    }
  }
  adv = obj->glyphs[(idx * 5) + 2] + obj->extra; width += adv; total += adv;
  return width + total;
}
'''


def _all(source=SOURCE):
    return [text for _, text in search_loop_field_reload.variants(source, 'measure')]


def test_the_search_becomes_the_counted_loop_with_the_table_read_through_its_field():
    out = _all()
    assert len(out) == 4
    full = [t for t in out if 'if (obj->table != 0)' in t and '== ch)' in t]
    assert len(full) == 1
    text = full[0]
    assert ('for (k = 0; k < ((Rec *) obj->table)[idx].count; k++) {\n'
            '    if (((Rec *) obj->table)[idx].pairs[k * 2] == ch) { width -= (s8) ((Rec *) obj->table)[idx].pairs[k * 2 + 1]; break; }\n}') in text
    # the scaffolding goes: the volatile read, the identical arms, the dead copies, the local pointer
    assert 'volatile *' not in text and 'for (;;)' not in text and 'continue' not in text
    assert 'off = ' not in text and 'table = obj->table;' not in text


def test_each_piece_is_also_offered_alone():
    out = _all()
    assert any('table = obj->table;' in t and '== key)' in t and 'for (k = 0;' in t for t in out)
    assert any('table = obj->table;' in t and '== ch)' in t for t in out)
    assert any('table = obj->table;' not in t and '== key)' in t and 'off = ' in t for t in out)


def test_another_shape_is_left_alone():
    assert search_loop_field_reload.variants(SOURCE.replace('k++;', 'k += 2;'), 'measure') == []
    assert search_loop_field_reload.variants('void f(void) { }', 'f') == []


def test_the_scratch_array_is_shortened_one_word_at_a_time():
    out = [t for _, t in frame_padding_repairs.shrink_variants(SOURCE, 'measure')]
    assert [t.count('volatile u32 pad[') for t in out] == [1, 1, 1]
    assert [next(line for line in t.splitlines() if 'volatile u32 pad[' in line).strip() for t in out] == [
        'volatile u32 pad[3];', 'volatile u32 pad[2];', 'volatile u32 pad[1];']
    # one that is read is not padding, and a lone word has nothing to shorten
    assert frame_padding_repairs.shrink_variants(SOURCE.replace('width = 0;', 'width = pad[0];'), 'measure') == []
    assert frame_padding_repairs.shrink_variants(SOURCE.replace('pad[4]', 'pad[1]'), 'measure') == []


def test_a_value_and_the_totals_it_feeds_are_wrapped_together():
    out = [t for _, t in accumulation_run_scope.variants(SOURCE, 'measure')]
    assert len(out) == 2
    assert 'do { adv = obj->glyphs[(idx * 5) + 2] + obj->extra; width += adv; total += adv; } while (0);' in out[0]
    assert out[1].count('do {') == 2
    wrapped = out[0]
    assert accumulation_run_scope.variants(wrapped, 'measure') == []


def test_the_whole_chain_from_the_saved_shape():
    child = next(t for t in _all() if 'if (obj->table != 0)' in t and '== ch)' in t)
    shrunk = [t for _, t in frame_padding_repairs.shrink_variants(child, 'measure')][-1]
    final = [t for _, t in accumulation_run_scope.variants(shrunk, 'measure')][0]
    assert 'pad[1]' in final and 'while (0)' in final and 'obj->table' in final

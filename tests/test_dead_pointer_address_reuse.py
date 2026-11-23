"""dead_pointer_address_reuse: a dead pointer local reused for the table a loop walks, with the scope moved to the loop."""
from decomprepair import dead_pointer_address_reuse as d

SOURCE = '''extern u8 head;
extern u8 rows;
s32 look(u8 v);
void put(u8 *p, s32 n);
void touch(u8 *p);

void refresh(void)
{
  s32 i;
  do
  {
    if (look(1) == 5)
    {
      u8 *cursor = &head;
      s32 v;
      v = look(*cursor);
      *cursor = v;
      cursor += 0x1C;
      put(cursor, v);
      i = 0;
      do
      {
        touch(&rows + i * 8);
        i += 1;
      }
      while (i < 14);
      put(&rows, 1);
    }
    return;
  }
  while (0);
}
'''


def test_the_reuse_alone_points_the_dead_pointer_at_the_loops_table():
    found = [text for family, text in d.variants(SOURCE, 'refresh') if family == d.REUSE]
    assert len(found) == 1
    text = found[0]
    assert 'cursor = (u8 *) &rows;' in text and 'touch(cursor + i * 8);' in text
    assert 'put(&rows, 1);' in text and text.count('while (0);') == 1


def test_the_scope_shift_child_starts_a_fence_at_the_loop_and_unwraps_the_outer_one():
    found = [text for family, text in d.variants(SOURCE, 'refresh') if family == d.SHIFT]
    assert len(found) == 1
    text = found[0]
    assert text.count('while (0);') == 1
    assert text.index('cursor = (u8 *) &rows;') < text.index('do {') < text.index('touch(cursor + i * 8);')
    assert text.index('while (0);') > text.index('while (i < 14);') and text.index('while (0);') < text.index('return;')


def test_nothing_when_the_pointer_is_still_used_after_the_loop():
    source = SOURCE.replace('      put(&rows, 1);\n', '      put(cursor, 1);\n')
    assert d.variants(source, 'refresh') == []


def test_nothing_without_a_loop_that_reads_another_symbols_address():
    source = SOURCE.replace('touch(&rows + i * 8);', 'touch(&head + i * 8);')
    assert d.variants(source, 'refresh') == []

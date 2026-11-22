"""A loop counter's constant start, weighted by one-shot scopes (and moved ahead of its guard)."""
from decomprepair import loop_weight_repairs as w

SOURCE = '''void f(s16 n, SearchEdge *edges, SearchRow *rows)
{
  volatile unsigned short pad;
  s32 j;
  {
    s32 k;
    if (n > 0)
    {
      SearchRow *table = rows;
      k = 0;
      do
      {
        s16 a = edges[k].a;
        for (j = 0; j < 16; j++)
        {
          if (table[a].links[j] == 0)
          {
            break;
          }
        }
        k++;
      }
      while (k < n);
    }
  }
}
'''


def test_counter_start_is_wrapped_in_place_and_ahead_of_the_guard():
    out = [text for _, text in w.variants(SOURCE, 'f')]
    wrapped = 'do {do { k = 0; } while (0);} while (0);'
    # in place (the guard's block keeps the start where it was)
    assert any(wrapped in text and text.index(wrapped) > text.index('if (n > 0)') for text in out)
    # ahead of the guard: the counter's range grows by the guard, and the block no longer holds the start
    ahead = [text for text in out if wrapped in text and text.index(wrapped) < text.index('if (n > 0)')]
    assert ahead and all('      k = 0;' not in text and text.count('k = 0;') == 1 for text in ahead)
    # every variant keeps the one-shot marker the family uses to avoid stacking
    assert all('__repair_loop_weight' in text for text in out[:6])


def test_a_used_counter_start_is_left_alone_when_the_counter_is_read_first():
    source = SOURCE.replace('SearchRow *table = rows;', 'SearchRow *table = rows + k;')
    out = [text for _, text in w.variants(source, 'f')]
    assert not any(text.index('k = 0;') < text.index('if (n > 0)') for text in out if 'do {do { k = 0;' in text)


def test_an_unreferenced_volatile_scratch_does_not_disable_the_family_but_a_used_one_does():
    assert w.variants(SOURCE, 'f')
    used = SOURCE.replace('  s32 j;', '  s32 j;\n  pad = 1;')
    assert w.variants(used, 'f') == []

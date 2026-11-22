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


SINK_SOURCE = '''void f(u8 n)
{
  s32 i;
  s32 r;
  i = 0;
  setup(1);
  g_flag = 2;
  r = count(n);
  if (r & 0xFF)
  {
    do
    {
      step(i & 0xFFFF);
      i += 1;
    }
    while ((i & 0xFFFF) < r);
  }
}
'''


def test_a_counter_start_written_ahead_of_unrelated_statements_is_sunk_to_its_guard():
    """A counter set before several calls it never meets has their length as live range: its priority drops below
    the loop's other temporary and the two saved registers swap (a KMC 2.7.2 save-slot menu loop, 120 -> 0)."""
    out = [text for family, text in w.variants(SINK_SOURCE, 'f') if family == w.COUNTER_SINK]
    assert out
    full, one_short = out[0], out[1]
    assert full.count('i = 0;') == 1 and full.index('i = 0;') > full.index('r = count(n);')
    assert full.index('i = 0;') < full.index('if (r & 0xFF)')
    # one statement short: the start sits between the last two crossed statements
    assert one_short.index('g_flag = 2;') < one_short.index('i = 0;') < one_short.index('r = count(n);')


def test_a_counter_start_is_not_sunk_past_a_statement_that_reads_it_or_when_its_address_is_taken():
    read = SINK_SOURCE.replace('g_flag = 2;', 'g_flag = i;')
    moved = [text for family, text in w.variants(read, 'f') if family == w.COUNTER_SINK]
    assert all(text.index('i = 0;') < text.index('g_flag = i;') for text in moved)
    escaped = SINK_SOURCE.replace('setup(1);', 'setup(&i);')
    assert not [1 for family, _ in w.variants(escaped, 'f') if family == w.COUNTER_SINK]
    adjacent = SINK_SOURCE.replace('  setup(1);\n  g_flag = 2;\n  r = count(n);\n', '').replace('  i = 0;\n', '  r = count(n);\n  i = 0;\n')
    assert not [1 for family, _ in w.variants(adjacent, 'f') if family == w.COUNTER_SINK]

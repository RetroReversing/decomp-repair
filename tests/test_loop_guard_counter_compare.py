from decomprepair.loop_guard_counter_compare import FAMILY, variants

SOURCE = """extern void g(int);
void f(int n)
{
  u32 count;
  u32 i;
  u32 j;
  count = n;
  i = 0;
  j = 5;
  if (count != 0)
  {
    do
    {
      g(i);
      i += 1;
    }
    while (i < count);
  }
}
"""


def test_the_guard_names_the_counter_that_is_zero_there():
    [(family, revised)] = variants(SOURCE, 'f')
    assert family == FAMILY
    assert '  if (i < count)\n' in revised and 'count != 0' not in revised
    assert revised.count('while (i < count)') == 1


def test_a_greater_than_guard_is_offered_for_a_signed_count_but_not_not_equal():
    signed = SOURCE.replace('u32 count;', 's32 count;')
    assert variants(signed, 'f') == []
    [(_, revised)] = variants(signed.replace('count != 0', 'count > 0'), 'f')
    assert '  if (i < count)\n' in revised


def test_the_counter_must_still_be_zero_and_its_loop_test_must_follow():
    # written between the zero and the guard
    assert variants(SOURCE.replace('  j = 5;', '  i += 2;'), 'f') == []
    assert variants(SOURCE.replace('  j = 5;', '  i = 3;'), 'f') == []
    # its address escapes
    assert variants(SOURCE.replace('  j = 5;', '  g(&i);'), 'f') == []
    # the loop does not test it against the count
    assert variants(SOURCE.replace('while (i < count)', 'while (j < count)'), 'f') == []
    # not a block guard, or a goto in the function
    assert variants(SOURCE.replace('  if (count != 0)\n  {', '  if (count != 0) g(1);\n  {'), 'f') == []
    assert variants(SOURCE.replace('  j = 5;', '  goto done;\n  done:'), 'f') == []


TWO_ROLES = """extern void g(int);
extern int h(int);
void f(int n)
{
  u32 count;
  u32 i;
  u32 biggest;
  u32 later;
  count = n;
  i = 0;
  biggest = 0;
  if (count != 0)
  {
    do
    {
      if (biggest < h(i))
      {
        biggest = h(i);
      }
      i += 1;
    }
    while (i < count);
  }
  g(biggest);
  later = h(2);
  g(later);
  g(later + 1);
}
"""


def test_every_merge_of_the_guarded_text_is_offered_as_one_combined_child():
    # the guard alone only moves the allocation; it pays off with the second role merged into the first
    children = [text for family, text in variants(TWO_ROLES, 'f') if family == FAMILY]
    plain = [text for text in children if 'later' in text and 'biggest = h(2)' not in text]
    assert any('if (i < count)' in text and 'later' in text for text in plain)
    merged = [text for text in children if 'if (i < count)' in text and 'biggest = h(2)' in text]
    assert merged and all('u32 later;' not in text for text in merged)
    assert all(text != TWO_ROLES for text in children)


LATCH = """extern void g(int);
void f(int n, int m)
{
    volatile u64 scratch[3];
    s32 count;
    s32 total;
    s32 i;
    count = n;
    total = m;
    i = 0;
    if (count > 0) {
    first: {
            g(i);
            i += 1;
        }
        if (i < count) goto first;
    }
    i = 0;
    if (total > 0) {
    second: {
            g(i + 1);
            i += 1;
        }
        if (i < total) goto second;
    }
}
"""


def test_a_latch_loop_closed_by_a_goto_is_offered():
    children = [text for family, text in variants(LATCH, 'f') if family == FAMILY]
    assert any('if (i < count) {' in text and 'if (count > 0)' not in text for text in children)
    assert any('if (i < total) {' in text and 'if (total > 0)' not in text for text in children)


def test_every_guard_is_one_child_and_the_scratch_it_replaces_another():
    children = [text for family, text in variants(LATCH, 'f') if family == FAMILY]
    everything = [text for text in children if 'if (count > 0)' not in text and 'if (total > 0)' not in text]
    assert everything and any('scratch' in text for text in everything)
    assert any('scratch' not in text for text in everything)  # the padding dropped with the guards
    assert all(text != LATCH for text in children)


def test_a_goto_into_the_block_or_out_of_it_is_declined():
    entered = LATCH.replace('    i = 0;\n    if (total', '    if (m) goto first;\n    i = 0;\n    if (total')
    assert not any('if (i < count) {' in text for _, text in variants(entered, 'f'))
    left = LATCH.replace('g(i);\n            i += 1;', 'g(i);\n            if (m) goto second;\n            i += 1;')
    assert not any('if (i < count) {' in text for _, text in variants(left, 'f'))

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
    # not a block guard
    assert variants(SOURCE.replace('  if (count != 0)\n  {', '  if (count != 0) g(1);\n  {'), 'f') == []


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


GLOBAL_COUNT_GOTO_LOOP = """extern void g(int);
extern unsigned char gCount;
void f(void)
{
  u32 i;
  i = 0;
  if (gCount != 0)
  {
top:
    {
      g(i);
      i += 1;
    }
    if (i < (u8) gCount) goto top;
  }
}
"""


def test_a_count_read_from_a_global_and_a_goto_loop_closing_test_are_offered():
    # m2c writes a counted loop over a byte global as `if (g != 0) { L: ...; if (i < (u8) g) goto L; }`
    [(family, revised)] = variants(GLOBAL_COUNT_GOTO_LOOP, 'f')
    assert family == FAMILY
    assert '  if (i < gCount)\n' in revised and 'gCount != 0' not in revised
    assert 'goto top' in revised


def test_a_signed_global_count_is_not_offered_for_not_equal():
    assert variants(GLOBAL_COUNT_GOTO_LOOP.replace('unsigned char', 'int'), 'f') == []

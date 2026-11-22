"""A one-shot `do { } while (0)` scope that a goto jumps into and another leaves is taken off."""
from decomprepair import crossing_scope_unwrap as m

# A scan over 4-byte records written as a goto loop: the scope at the loop head holds the `scan:` label, entered from the
# loop's tail and left by `goto advance`, so the scopes that need self-contained gotos refuse it.
SOURCE = '''s32 pick(void *actor, Rec *recs, s32 count)
{
  u32 index;
  u32 threshold;
  u32 limit;
  u8 *entry;
  u16 id;
  threshold = rnd(count);
  do
  {
    limit = count - 1;
    do
    {
      entry = (u8 *) recs;
      scan:
      if (entry[4] < threshold)
      {
        index++;
        goto advance;
      }
      id = *((u16 *) (entry + 2));
    }
    while (0);
    if (id == 0)
    {
      return 0;
    }
    use(actor, id);
    advance:
    entry += 4;
    if (index < limit)
    {
      goto scan;
    }
  }
  while (0);
  return 0;
}
'''


INNER_OFF = SOURCE.replace("    do\n    {\n      entry", "    {\n      entry").replace(
    "    }\n    while (0);\n    if (id == 0)", "    }\n    if (id == 0)")
OUTER_OFF = SOURCE.replace("  do\n  {\n    limit", "  {\n    limit").replace(
    "  }\n  while (0);\n  return 0;", "  }\n  return 0;")


def test_the_scope_the_loop_jumps_into_is_taken_off_alone_and_so_is_the_outer_one():
    found = m.variants(SOURCE, 'pick')
    assert {family for family, _ in found} == {'crossing_scope_unwrap'}
    texts = [text for _, text in found]
    assert INNER_OFF != SOURCE and OUTER_OFF != SOURCE
    assert INNER_OFF in texts and OUTER_OFF in texts


def test_every_crossing_scope_off_at_once_is_one_child():
    both = INNER_OFF.replace("  do\n  {\n    limit", "  {\n    limit").replace(
        "  }\n  while (0);\n  return 0;", "  }\n  return 0;")
    assert 'while (0)' not in both
    assert both in [text for _, text in m.variants(SOURCE, 'pick')]


def test_a_scope_with_a_break_or_a_declaration_is_left_alone():
    with_break = SOURCE.replace('index++;\n        goto advance;', 'break;')
    assert m.variants(with_break, 'pick') == []
    declared = '''void f(int a)
{
  do
  {
    int t;
    t = g(a);
    if (t) { goto out; }
    h(t);
    out:
    k(a);
  }
  while (0);
}
'''
    assert m.variants(declared, 'f') == []


def test_a_scope_with_no_label_or_goto_is_not_this_families_to_touch():
    plain = 'void f(int a)\n{\n  do\n  {\n    g(a);\n  }\n  while (0);\n}\n'
    assert m.variants(plain, 'f') == []

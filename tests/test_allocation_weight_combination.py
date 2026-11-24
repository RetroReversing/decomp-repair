"""Edits that only pay off together: unwrap one-shot scopes with labels, collapse a spill-slot copy, sink an init."""
from decomprepair import allocation_weight_combination as m

SOURCE = '''void f(s32 *arg0) {
  s32 *slot;
  s32 *temp;
  s32 *next;
  s32 *res;
  s32 *keep;
  do
  {
    res = NULL;
    if (arg0 != NULL)
    {
      temp = &arg0[g(1)]; next = &temp[g(1)]; slot = temp;
      h(next);
      do
      {
        k(res);
      }
      while (0);
      if (res != NULL)
      {
        goto out;
      }
      keep = slot;
      h(keep);
      out:
      h(res);
    }
  }
  while (0);
}
'''


def by_family():
    out = {}
    for family, text in m.variants(SOURCE, 'f'):
        out.setdefault(family, []).append(text)
    return out


def test_each_edit_alone_and_the_combination():
    found = by_family()
    assert set(found) == set(m.FAMILIES)
    everything = [t for t in found['weight_combination']
                  if 'while (0)' not in t and 'slot = &arg0[g(1)]; next = &slot[g(1)];' in t]
    assert everything, 'the all-edits child is offered'
    best = everything[0]
    assert 'slot = temp' not in best
    assert best.index('if (arg0 != NULL)') < best.index('res = NULL;')
    for family in ('weight_scope_unwrap', 'spill_slot_copy_collapse', 'init_sink_into_guard'):
        assert all(t != SOURCE for t in found[family])


def test_collapse_needs_a_single_assignment():
    twice = SOURCE.replace('keep = slot;', 'slot = next; keep = slot;')
    assert 'spill_slot_copy_collapse' not in {f for f, _ in m.variants(twice, 'f')}


def test_wrapper_with_a_goto_leaving_it_stays():
    outside = SOURCE.replace('  while (0);\n}', '  while (0);\n  if (x) { goto out; }\n}')
    for family, text in m.variants(outside, 'f'):
        if family in ('weight_scope_unwrap', 'weight_combination'):
            assert text.count('while (0)') >= 1 and text.count('do\n') >= 1 and text.index('do\n') < text.index('res = NULL')


SINKS = """void g(int);
void f(int n, int m, int c)
{
  int i;
  int j;
  int v;
  v = 1;
  if (!(c > 0))
  {
    v = 0;
  }
  i = 0;
  if (n > 0)
  {
    do { g(i); i++; } while (i < n);
  }
  j = 0;
  if (m > 0)
  {
    do { g(j); j++; } while (j < m);
  }
  g(v);
}
"""


def test_every_guarded_counter_init_is_a_child_and_a_flag_is_never_sunk():
    from decomprepair import allocation_weight_combination as awc
    texts = [t for fam, t in awc.variants(SINKS, 'f') if fam == 'init_sink_into_guard']
    assert any('if (n > 0)\n  {\n      i = 0;' in t and '  j = 0;\n  if (m > 0)' in t for t in texts)
    assert any('if (m > 0)\n  {\n      j = 0;' in t and '  i = 0;\n  if (n > 0)' in t for t in texts)
    assert all('  v = 1;\n  if (!(c > 0))' in t for t in texts)

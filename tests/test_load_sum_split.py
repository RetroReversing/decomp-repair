"""A field read plus an offset written as the load and then `+=`."""
import re

from decomprepair.load_sum_split import variants

BEFORE = '''void f(s32 *t, u16 *tab, u32 mask)
{
  void *p;
  void *q;
  u32 i;
  s32 off;
  i = 0;
  off = 0;
  do
  {
    p = ((Field_s32 *) (((char *) t) + 0x3C))->v + off;
    if ((mask & tab[i]) && (mask & i))
    {
      g(p);
    }
    q = *(void **) t + off;
    off += 6;
    i += 1;
  }
  while (i < 4);
}
'''


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def _all(text, name='f'):
    return [src for fam, src in variants(text, name) if fam == 'load_sum_split']


def test_each_site_and_all_sites_are_offered():
    found = [_squash(src) for src in _all(BEFORE)]
    assert any('p = ((Field_s32 *) (((char *) t) + 0x3C))->v; p += off;' in t and 'q = *(void **) t + off;' in t for t in found)
    assert any('q = *(void **) t; q += off;' in t and 'p += off;' in t for t in found)
    assert len(found) == 3


def test_a_sum_of_two_locals_has_no_load_to_split():
    assert _all(BEFORE.replace('((Field_s32 *) (((char *) t) + 0x3C))->v + off', 'i + off').replace('*(void **) t + off', 'i + off')) == []


def test_other_processors_are_not_offered_it():
    assert variants(BEFORE, 'f', 'ppc') == []


# m2c's other spelling: the load has a name of its own, the sum is the next statement.
PAIR = '''void f(s32 *t, u16 *tab, u32 mask)
{
  void *p;
  s32 raw;
  u32 i;
  s32 off;
  i = 0;
  off = 0;
  do
  {
    raw = ((Field_s32 *) (((char *) t) + 0x3C))->v; p = raw + off;
    if (mask & tab[i])
    {
      g(p);
    }
    off += 6;
    i += 1;
  }
  while (i < 4);
}
'''


def test_the_named_load_and_its_sum_become_one_local_with_two_sets():
    found = [_squash(src) for src in _all(PAIR)]
    assert any('p = ((Field_s32 *) (((char *) t) + 0x3C))->v; p += off;' in t and 'raw =' not in t for t in found)


def test_a_named_load_that_is_read_again_is_kept():
    assert _all(PAIR.replace('g(p);', 'g(p + raw);')) == []

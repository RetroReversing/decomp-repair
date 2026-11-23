"""The second test of an `&&` pair carried by an integer local that is dead there."""
import re

from decomprepair.condition_value_reuse import variants

BEFORE = '''void f(u16 *tab, u32 mask, u32 a, u32 b)
{
  u32 r;
  u32 spare;
  u32 i;
  r = (u16) g(a);
  a = r & 0xFF;
  b = r & 0xFF00;
  spare = 0;
  i = 0;
  do
  {
    if ((a & tab[i]) && (b & tab[i]))
    {
      h(i);
    }
    i += 1;
  }
  while (i < 4);
  spare = 1;
}
'''


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def _all(text, name='f'):
    return [src for fam, src in variants(text, name) if fam == 'condition_value_reuse']


def test_the_second_test_is_carried_by_a_dead_local():
    found = [_squash(src) for src in _all(BEFORE)]
    assert any('if ((a & tab[i]) && ((r = b & tab[i]) != 0))' in t for t in found)
    assert any('((spare = b & tab[i]) != 0)' in t for t in found)


def test_a_local_the_loop_still_reads_is_not_used():
    reads = BEFORE.replace('h(i);', 'h(spare);')
    assert not any('(spare =' in _squash(src) for src in _all(reads))


def test_a_condition_with_a_call_is_left_alone():
    assert _all(BEFORE.replace('(b & tab[i])', 'k(b)')) == []


def test_other_processors_are_not_offered_it():
    assert variants(BEFORE, 'f', 'ppc') == []

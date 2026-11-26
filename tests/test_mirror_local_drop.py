"""A local that always holds the walked variable, written as that variable."""
from decomprepair import mirror_local_drop as t

SOURCE = '''s32 walk(u16 node)
{
  s32 at;
  s32 count;

  count = 1;
  at = node;
  if (T[node].next != 0xFFFF)
  {
    do
    {
      node = T[at].next;
      at = node;
      count++;
    }
    while (T[at].next != 0xFFFF);
  }
  return count + node;
}
'''


def test_the_mirror_goes_and_the_guarded_do_becomes_a_while():
    out = [text for _, text in t.variants(SOURCE, 'walk')]
    assert 'while (T[node].next != 0xFFFF) {' in out[0] and 'do' not in out[0]
    assert 'node = T[node].next;' in out[0] and 'at =' not in out[0]
    assert any('do' in text and 'at =' not in text for text in out[1:])


def test_a_masked_copy_is_a_mirror_of_a_u16():
    source = SOURCE.replace('at = node;\n      count', 'at = node & 0xFFFF;\n      count')
    assert any('at =' not in text for _, text in t.variants(source, 'walk'))


def test_a_copy_that_falls_behind_is_kept():
    # `node` steps without `at` following, so `at` holds the previous node.
    stale = SOURCE.replace('      at = node;\n      count++;', '      count++;\n      at = node;')
    assert t.variants(stale, 'walk') == []


def test_a_narrower_copy_is_kept():
    source = SOURCE.replace('s32 at;', 'u8 at;')
    assert t.variants(source, 'walk') == []

"""A loop's invariant `(p + (e))[i]` base written through a pointer set before the loop."""
from decomprepair.loop_subscript_base_pointer import FAMILY, variants

# The last pass of a bit-stream decoder's table builder (KMC GCC 2.7.2, N64): the second-level table's base is
# invariant in the innermost loop and written inline.
PASS = '''void f(u16 *tab, u32 *t, u32 *l, u32 k, u32 tb, u32 step)
{
  u32 a;
  u32 y;
  do {
    u16 ent;
    a = t[k];
    ent = tab[a & 7];
    y = a >> tb;
    a = (ent >> 4) & 7;
    do {
      (tab + ((ent >> 7) + step))[y] = l[k];
      y += 1 << (l[k] - tb);
    } while ((y >> a) == 0);
    k++;
  } while (k < 9);
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_base_is_set_at_each_boundary_after_its_last_write():
    kids = _children(PASS)
    assert len(kids) == 3
    for kid in kids:
        assert '    u16 *sb;\n' in kid
        assert 'sb[y] = l[k];' in kid and '(tab + ((ent >> 7) + step))' not in kid
    assert '    ent = tab[a & 7];\n    sb = tab + ((ent >> 7) + step);\n    y = a >> tb;' in kids[0]
    assert '    a = (ent >> 4) & 7;\n    sb = tab + ((ent >> 7) + step);\n    do {' in kids[2]


def test_a_base_the_loop_writes_is_left_alone():
    text = PASS.replace('      y += 1', '      step++;\n      y += 1')
    assert _children(text) == []


def test_a_subscript_outside_any_loop_is_left_alone():
    text = '''void f(u16 *tab, u32 i, u32 e)
{
  (tab + (e + 1))[i] = 0;
}
'''
    assert _children(text) == []

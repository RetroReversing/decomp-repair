"""A product with a u16 counter as a u16 product."""
from decomprepair.counter_product_cast import FAMILY, FAMILY_SUM, variants

SAVED = '''void f(Rec *r, s32 X)
{
  u16 i, j;
  s32 tx, ty;
  for (i = 0; i < 3; i++)
  {
    for (j = 0; j < 4; j++)
    {
      tx = r->tw * i + r->x + X;
      ty = r->y + r->th * j;
      g(tx, ty);
    }
  }
}
'''


def _squash(text):
    return ' '.join(text.split())


def _children(source, family):
    return [_squash(src) for fam, src in variants(source, 'f') if fam == family]


def test_each_product_with_a_counter_is_cast_alone():
    out = _children(SAVED, FAMILY)
    assert len(out) == 2
    assert any('tx = (u16)(r->tw * i) + r->x + X;' in c for c in out)
    assert any('ty = r->y + (u16)(r->th * j);' in c for c in out)


def test_the_whole_sum_is_cast_too():
    out = _children(SAVED, FAMILY_SUM)
    assert any('tx = (u16)(r->tw * i + r->x + X);' in c for c in out)
    assert any('ty = (u16)(r->y + r->th * j);' in c for c in out)


def test_a_product_already_cast_and_a_wide_counter_give_no_child():
    cast = SAVED.replace('r->tw * i + r->x + X', '(u16)(r->tw * i) + r->x + X')
    assert not any('(u16)((u16)' in c for c in _children(cast, FAMILY))
    assert _children(SAVED.replace('u16 i, j;', 's32 i, j;'), FAMILY) == []


def test_no_product_no_child():
    assert variants(SAVED.replace('r->th * j', 'r->th + j').replace('r->tw * i', 'r->tw + i'), 'f') == []

"""Positions built from a halfword loop counter typed as halfwords, with their `* 4` written `<< 2`."""
from decomprepair.halfword_position_shift import FAMILY, REPAIR, variants

SAVED = '''void f(s32 X, s32 Y, Spr *r)
{
  u16 i, j;
  s32 tx, ty, ly;
  s32 copy;
  s32 dsdx;
  dsdx = r->k / r->w;
  for (i = 0; i < r->rows; i++)
  {
    for (j = 0; j < r->cols; j++)
    {
      tx = r->cw * i + r->x + X; copy = tx;
      ty = r->y + r->ch * j;
      ly = ty + Y;
      rect((s16) (copy * 4), ly * 4, (tx + r->cw) * 4, (r->ch * 2 + ly) * 4, dsdx * 4);
    }
  }
}
'''


def _squash(text):
    return ' '.join(text.split())


def _children(source):
    return [_squash(src) for fam, src in variants(source, 'f') if fam == FAMILY]


def test_positions_are_retyped_and_their_products_shifted_in_one_child():
    first = _children(SAVED)[0]
    assert 'u16 tx; u16 ty; u16 ly;' in first and 'u16 copy;' in first
    assert 's32 dsdx;' in first  # not built from a counter
    assert ('rect((s16) ((copy << 2)), (ly << 2), ((tx + r->cw) << 2), ((r->ch * 2 + ly) << 2), dsdx * 4);'
            in first)
    assert 'tx = r->cw * i + r->x + X;' in first


def test_the_retyping_alone_is_offered_too():
    out = _children(SAVED)
    assert any('u16 tx;' in child and 'copy * 4' in child for child in out)


def test_a_signed_counter_gives_signed_positions():
    out = _children(SAVED.replace('u16 i, j;', 's16 i, j;'))
    assert 's16 tx; s16 ty; s16 ly;' in out[0]


def test_nothing_without_a_halfword_counter():
    assert _children(SAVED.replace('u16 i, j;', 's32 i, j;')) == []


def test_a_division_keeps_a_local_wide():
    source = SAVED.replace('ly = ty + Y;', 'ly = ty / Y;')
    first = _children(source)[0]
    assert 's32 ly;' in first and 'u16 ty;' in first


def test_a_product_inside_a_wider_product_is_left_alone():
    source = SAVED.replace('dsdx * 4);', 'dsdx / ly * 4);')
    assert 'dsdx / ly * 4' in _children(source)[0]


def test_the_module_declares_itself():
    assert REPAIR['families'] == (FAMILY,) and REPAIR['variants'] is variants


def test_a_child_puts_the_counter_product_last_in_its_sum():
    out = _children(SAVED)
    assert any('tx = r->x + X + r->cw * i;' in child and '(ly << 2)' in child for child in out)


def test_retyped_declarations_stay_one_per_line():
    child = variants(SAVED, 'f')[0][1]
    assert '\n  u16 tx;\n  u16 ty;\n  u16 ly;\n' in child

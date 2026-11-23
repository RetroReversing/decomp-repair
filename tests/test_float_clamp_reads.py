"""A field clamp's reads and an in-place product, as the game wrote them (a 1300-instruction routine, 550 -> 500)."""
from decomprepair.float_clamp_reads import FAMILY_MIN, FAMILY_PRODUCT, REPAIR, variants

SOURCE = """void speed(Obj *o, f32 x)
{
  f32 scale;
  f32 t;
  scale = 1.3f;
  t = o->top;
  if (t < o->cur)
  {
    o->cur = t;
  }
  if (x != 0.0f)
  {
    scale = o->max * scale;
    o->max = scale;
    if (o->cur < scale)
    {
      o->max = o->cur;
    }
  }
}
"""


def squash(text):
    return ' '.join(text.split())


def test_both_together_first_then_each():
    found = variants(SOURCE, 'speed')
    assert [family for family, _ in found] == [FAMILY_PRODUCT, FAMILY_MIN, FAMILY_PRODUCT]
    both = squash(found[0][1])
    assert 'if (o->cur > o->top) { o->cur = o->top; }' in both and 'f32 t;' not in both
    assert 'product = o->max * scale; o->max = product; if (o->cur < product)' in both
    assert 'f32 scale; f32 product;' in both


def test_a_temporary_read_elsewhere_is_kept():
    source = SOURCE.replace('  if (x != 0.0f)\n', '  use(t);\n  if (x != 0.0f)\n')
    assert all(family != FAMILY_MIN for family, _ in variants(source, 'speed'))


def test_a_product_read_after_its_block_is_kept():
    source = SOURCE.replace('    }\n  }\n}\n', '    }\n  }\n  use(scale);\n}\n')
    assert all(family != FAMILY_PRODUCT for family, _ in variants(source, 'speed'))


def test_it_declares_itself():
    assert REPAIR['variants'] is variants and set(REPAIR['families']) == {FAMILY_MIN, FAMILY_PRODUCT}

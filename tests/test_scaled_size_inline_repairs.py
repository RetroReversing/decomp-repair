from decomprepair import scaled_size_inline_repairs as scaled

SOURCE = '''extern s16 gFlag;
extern s32 gBuf;
s32 heapAlloc(s32, s32);
extern s32 *gSlots[];
void f(void)
{
  s32 size;
  s32 buf;
  s32 i;
  size = 0x800;
  if (gFlag != 0)
  {
    size = 0x4000;
  }
  size *= 8;
  gBuf = heapAlloc(size, 0);
  for (i = 0; i < 3; i++)
  {
    if (gSlots[i] != 0)
    {
      buf = gBuf;
      gSlots[i][0] = buf;
      gSlots[i][1] = buf + size;
    }
  }
}
'''


def test_scale_moves_to_each_read():
    (family, text), = scaled.variants(SOURCE, 'f')
    assert family == scaled.FAMILY
    assert 'size *= 8;' not in text
    assert 'heapAlloc((size * 8), 0)' in text and 'buf + (size * 8)' in text
    assert 'size = 0x4000;' in text


def test_shift_and_self_product_forms():
    for form in ('size <<= 3;', 'size = size * 8;', 'size = size << 3;'):
        (_, text), = scaled.variants(SOURCE.replace('size *= 8;', form), 'f')
        assert form not in text and '(size ' in text


def test_refuses_when_the_value_changes_or_is_read_once():
    assert not scaled.variants(SOURCE.replace('  size *= 8;', '  size *= 8;\n  size += 1;'), 'f')
    assert not scaled.variants(SOURCE.replace('buf + size', 'buf'), 'f')
    assert not scaled.variants(SOURCE.replace('heapAlloc(size, 0)', 'heapAlloc(1, 0)'), 'f')
    nested = SOURCE.replace('  size *= 8;', '  if (gFlag)\n  {\n    size *= 8;\n  }')
    assert not scaled.variants(nested, 'f')


def test_sixteen_bit_cast_on_the_sum_is_a_second_child():
    cast = SOURCE.replace('buf + size;', '(unsigned short) (buf + size);')
    texts = [t for _, t in scaled.variants(cast, 'f')]
    assert len(texts) == 2
    assert any('(unsigned short)' in t for t in texts) and any('(unsigned short)' not in t for t in texts)
    assert any('gSlots[i][1] = (buf + (size * 8));' in t for t in texts)

"""Two byte-valued locals held as 16-bit values, with the game's own mask helper shared."""
from decomprepair import masked_byte_pair_repairs as m

SOURCE = '''inline static s32 low_byte(u32 arg0)
{
  return (s32) (arg0 & 0xFF);
}

s32 f(u8 *p, s32 r)
{
  u32 hi;
  u32 lo;
  s32 n;
  u32 w = *((u32 *) p);
  lo = w >> 8;
  hi = w >> 24;
  if (hi < (lo & 0xFF))
  {
    u32 tmp = lo;
    lo = hi; hi = tmp;
  }
  n = (hi & 0xFF) - low_byte(lo);
  return ((lo & 0xFF) + r) << n;
}
'''


def test_the_pair_is_narrowed_and_the_mask_shared():
    # A KMC N64 function: 380 -> 180 as one child (each step alone was worse).
    (family, out), (_, narrow_only) = m.variants(SOURCE, 'f')
    assert family == 'masked_byte_pair'
    assert '  u16 hi;\n  u16 lo;\n' in out
    assert '  lo = (u16)(w >> 8);\n  hi = (u16)(w >> 24);\n' in out
    assert 'if ((u8)hi < (u8)lo)' in out
    assert '    u16 tmp = lo;\n' in out
    assert 'return (low_byte(lo) + r) << n;' in out
    assert 'return ((lo & 0xFF) + r) << n;' in narrow_only  # the helper step is its own difference


def test_left_alone_without_a_byte_pair():
    assert m.variants(SOURCE.replace('(lo & 0xFF)', 'lo'), 'f') == []  # lo is no longer masked
    assert m.variants(SOURCE.replace('lo = w >> 8;', 'lo = w;'), 'f') == []  # lo is not unpacked
    assert m.variants(SOURCE.replace('  u32 hi;\n', ''), 'f') == []  # one local is not a pair
    assert m.variants(SOURCE, 'missing') == []

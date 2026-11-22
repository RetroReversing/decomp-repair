"""The three rewrites compose: each applies to the output of the one before, on one function."""
from decomprepair import compare_arm_split_repairs, masked_byte_pair_repairs, or_constant_stage_repairs

SOURCE = '''inline static s32 low_byte(u32 arg0)
{
  return (s32) (arg0 & 0xFF);
}

inline static u8 find(u8 *obj, s32 key)
{
  u8 a;
  u8 b;
  u32 x;
  u32 y;
  if (key == (-1))
    return 0;
  a = obj[0x10];
  b = obj[0x11];
  y = key;
  if (b == 0xFF)
    x = flat[(u8)y];
  else
  {
    u8 *row = grid + (b << 4);
    x = row[a];
  }
  if (x == (u8)y)
    return 1;
  return 0;
}

s32 f(u8 *obj, u8 *p, s32 pitch, s32 r)
{
  u32 hi;
  u32 lo;
  u32 w = *((u32 *) p);
  lo = w >> 8;
  hi = w >> 24;
  if (hi < (lo & 0xFF))
  {
    u32 tmp = lo;
    lo = hi; hi = tmp;
  }
  r = r % ((((s32) (hi & 0xFF)) - low_byte(lo)) + 1);
  *((s32 *) p) = (((pitch & 0xFF) << 16) | (((lo & 0xFF) + r) << 8)) | 0x19;
  return find(obj, *((s32 *) (obj + 0x60)));
}
'''


def test_the_whole_chain():
    # The KMC N64 function these came from went 380 -> 265 -> 65 -> 0 in this order.
    source = compare_arm_split_repairs.variants(SOURCE, 'f')[-1][1]
    source = masked_byte_pair_repairs.variants(source, 'f')[0][1]
    source = or_constant_stage_repairs.variants(source, 'f')[0][1]
    assert '    u8 *row = __repair_base + __repair_off;' in source
    assert '  u16 lo;' in source and '(low_byte(lo) + r)' in source
    assert 'u32 __repair_or = ((low_byte(lo) + r) << 8) | 0x19;' in source

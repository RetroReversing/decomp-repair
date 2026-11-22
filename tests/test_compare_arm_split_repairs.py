"""A two-table lookup's compare written into each arm, with the key copy pinned."""
from decomprepair import compare_arm_split_repairs as c

SOURCE = '''inline static u8 find(u8 *obj, s32 key)
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
'''


def test_each_step_adds_one_edit():
    # A KMC N64 helper: 255 -> 80 -> 60 -> 0, each child from the one before.
    first, second, third = [out for _, out in c.variants(SOURCE, 'f')]
    for out in (first, second, third):
        assert '  y = key;\n  key = 0;\n  key = y;\n' in out
        assert out.count('if (x == (u8)y)') == 1  # the compare left the join
    assert '    x = flat[(u8)y];\n    if (x != (u8)y)\n      return 0;\n    return 1;\n' in first
    assert '    if (flat[(u8)y] != (u8)y)\n      return 0;\n    return 1;\n' in second
    assert 'u8 *row = grid + (b << 4);' in second
    assert ('    u8 *__repair_base = grid;\n    u32 __repair_off = b << 4;\n'
            '    u8 *row = __repair_base + __repair_off;\n') in third
    assert third.count('return 1;') == 2


def test_left_alone_otherwise():
    assert c.variants(SOURCE.replace('x == (u8)y', 'x == y'), 'f') == []  # not a byte compare
    assert c.variants(SOURCE.replace('  if (x == (u8)y)', '  if (x == (u8)y && key)'), 'f') == []
    # the key is read again after the compare: pinning would change it
    assert c.variants(SOURCE.replace('  return 0;\n}\n', '  return key;\n}\n'), 'f') == []

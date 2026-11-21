from decomprepair import clamp_barrier_repairs as clamp

SOURCE = '''s32 f(u8 *arg0)
{
  u32 x;
  s32 t;
  s32 v;
  x = arg0[0x10];
  t = x - 0x20;
  if (t >= 0)
  {
    v = x - 0x20;
    if (t >= 0x25)
    {
      v = 0x24;
    }
  }
  else
  {
    v = 0;
  }
  return v;
}
'''


def test_the_first_difference_is_spelled_so_cse_cannot_share_it():
    out = [text for family, text in clamp.variants(SOURCE, 'f') if family == clamp.FAMILY]
    assert len(out) == 3
    assert 't = (s16) x - 0x20;' in out[0]
    assert 't = (x & 0xFF) - 0x20;' in out[1]
    assert 't = (s8) x - 0x20;' in out[2]
    assert all('v = x - 0x20;' in text for text in out)


def test_nothing_is_offered_without_the_second_difference():
    plain = SOURCE.replace('v = x - 0x20;', 'v = t;')
    assert clamp.variants(plain, 'f') == []


def test_a_changed_operand_between_the_two_is_left_alone():
    moved = SOURCE.replace('if (t >= 0)\n  {\n', 'if (t >= 0)\n  {\n    x = 3;\n')
    # the arm reassigns x before reading it: the second difference is not the same value
    assert clamp.variants(moved, 'f') == []


MANY = '''s32 f(u8 *arg0)
{
  u32 a;
  u32 b;
  s32 t;
  s32 u;
  s32 x;
  s32 y;
  a = arg0[0x10];
  t = a - 0x20;
  if (t >= 0)
  {
    x = a - 0x20;
    if (t >= 0x100) x = 0xFF;
  }
  else x = 0;
  b = *(u32 *) (arg0 + 0x10) >> 8;
  u = b - 0x20;
  if (u >= 0)
  {
    y = b - 0x20;
    if (u >= 0x61) y = 0x60;
  }
  else y = 0;
  return x + y;
}
'''


def test_every_clamp_at_once_is_offered_in_each_style_before_the_single_sites():
    out = [text for _, text in clamp.variants(MANY, 'f')]
    assert len(out) == 4 + 6
    assert 't = (s16) a - 0x20;' in out[0] and 'u = (s16) b - 0x20;' in out[0]
    assert 't = (a & 0xFF) - 0x20;' in out[1] and 'u = (b & 0xFF) - 0x20;' in out[1]
    # a byte load keeps the sign extension, the middle byte of a word takes the mask
    mixed = out[3]
    assert 't = (s16) a - 0x20;' in mixed and 'u = (b & 0xFF) - 0x20;' in mixed
    assert 't = (s16) a - 0x20;' not in out[4] or 'u = (s16) b' not in out[4]

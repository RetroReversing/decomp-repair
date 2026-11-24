"""An inline helper's parameter masked in both arms of an `if`, read through a byte copy made before it."""
from decomprepair.inline_param_byte_copy import FAMILY, variants

# A sound-sequence interpreter's slot-ownership test (KMC GCC 2.7.2, N64).
SRC = '''static inline s32 owns(u8 *voice, s32 id)
{
  u8 bank;
  s32 x;
  s32 y;
  if (id != -1)
  {
    bank = voice[0x4B];
    if (bank == 0xFF)
    {
      x = id & 0xFF;
      y = ids[x];
    }
    else
    {
      x = slots[bank];
      y = id & 0xFF;
    }
    if (x == y)
    {
      return 1;
    }
  }
  return 0;
}

void f(u8 *v)
{
  if (owns(v, v[0x60]))
  {
    act(v);
  }
}
'''


def test_the_masks_read_a_byte_copy_made_before_the_if():
    kids = [src for fam, src in variants(SRC, 'f') if fam == FAMILY]
    want = (SRC.replace('{\n  u8 bank;', '{\n  u8 slot;\n  u8 bank;', 1)
            .replace('    if (bank == 0xFF)', '    slot = id;\n    if (bank == 0xFF)')
            .replace('x = id & 0xFF;', 'x = slot;').replace('y = id & 0xFF;', 'y = slot;'))
    assert kids == [want]


def test_masks_in_one_arm_only_are_left_alone():
    text = SRC.replace('y = id & 0xFF;', 'y = 3;')
    assert [src for fam, src in variants(text, 'f') if fam == FAMILY] == []

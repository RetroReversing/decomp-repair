"""A narrow-sign clamp written as a wide sum tested by a shift, the positive arm falling through."""
from decomprepair.narrow_sign_clamp_shift_test import FAMILY, variants

# A sound-sequence interpreter's pan-offset command (KMC GCC 2.7.2, N64): byte field plus signed command byte.
ARM = '''void f(void *voice, u32 cmd)
{
  u16 level;
  level = (*((u8 *) (((char *) voice) + 0xC1))) + (((s32) (cmd << 0x10)) >> 0x18);
  *((u16 *) (((char *) voice) + 0x50)) = level;
  if (((s16) level) < 0)
  {
    level = 0;
  }
  else if (level >= 0x80)
  {
    level = 0x7F;
  }
  *((u16 *) (((char *) voice) + 0x50)) = level;
}
'''

WANT = '''void f(void *voice, u32 cmd)
{
  u16 level;
  {
  s32 sum;
  sum = (*((u8 *) (((char *) voice) + 0xC1))) + (((s32) (cmd << 0x10)) >> 0x18);
  *((u16 *) (((char *) voice) + 0x50)) = sum;
  if ((sum << 16) >= 0)
  {
    level = sum;
    if (level >= 0x80)
    {
      level = 0x7F;
    }
  }
  else
  {
    level = 0;
  }
  }
  *((u16 *) (((char *) voice) + 0x50)) = level;
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_sum_is_tested_by_a_shift_and_the_positive_arm_falls_through():
    kids = _children(ARM)
    assert len(kids) == 3 and kids[2] == WANT
    assert kids[1] == WANT.replace('  s32 sum;', '  s16 sum;')
    assert kids[0] == WANT.replace('  s32 sum;\n  sum = (*((u8 *) (((char *) voice) + 0xC1))) + (((s32) (cmd << 0x10)) >> 0x18);\n'
                                   '  *((u16 *) (((char *) voice) + 0x50)) = sum;\n',
                                   '  s16 sum;\n  *((u16 *) (((char *) voice) + 0x50)) = (*((u8 *) (((char *) voice) + 0xC1))) + '
                                   '(((s32) (cmd << 0x10)) >> 0x18);\n  sum = *((u16 *) (((char *) voice) + 0x50));\n')


def test_without_the_store_of_the_raw_sum():
    text = ARM.replace("  *((u16 *) (((char *) voice) + 0x50)) = level;\n  if", "  if", 1)
    kids = _children(text)
    assert len(kids) == 2
    assert '= sum;\n  if ((sum << 16) >= 0)' not in kids[0] and 'sum = (*((u8' in kids[0]


def test_a_used_name_is_not_reused():
    text = ARM.replace('u16 level;', 'u16 level;\n  s32 sum = 0;')
    kids = _children(text)
    assert len(kids) == 3 and 's32 sum2;' in kids[2]


def test_a_wide_sign_test_is_left_alone():
    assert _children(ARM.replace('((s16) level) < 0', 'level < 0')) == []


def test_the_value_read_in_its_own_sum_is_left_alone():
    assert _children(ARM.replace('(cmd << 0x10)', '(level << 0x10)')) == []


def test_a_byte_local_or_a_word_store_is_left_alone():
    assert _children(ARM.replace('u16 level;', 'u8 level;')) == []
    assert _children(ARM.replace('*((u16 *) (((char *) voice) + 0x50)) = level;\n  if', '*((s32 *) (((char *) voice) + 0x50)) = level;\n  if', 1)) == []

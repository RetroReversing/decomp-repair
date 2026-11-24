"""m2c's sign-extracting shift pair written as the signed cast it was."""
from decomprepair.shift_pair_sign_cast import FAMILY, variants

ARM = '''extern u32 D_800FDB9C;
void f(u8 *p, s32 w)
{
  s16 sum;
  u16 t;
  *((u16 *) (p + 0x50)) = p[0xC1] + (((s32) (D_800FDB9C << 0x10)) >> 0x18);
  p[0x10] = (((s32) ((u32) w << 8)) >> 0x10);
  sum = *((u16 *) (p + 0x50));
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_each_pair_becomes_a_cast_alone_and_together():
    kids = _children(ARM)
    byte = ARM.replace('(((s32) (D_800FDB9C << 0x10)) >> 0x18)', '((s8) (D_800FDB9C >> 8))')
    half = ARM.replace('(((s32) ((u32) w << 8)) >> 0x10)', '((s16) ((u32) w >> 8))')
    assert byte in kids and half in kids
    assert byte.replace('(((s32) ((u32) w << 8)) >> 0x10)', '((s16) ((u32) w >> 8))') in kids


def test_a_signed_word_is_left_alone():
    text = ARM.replace('extern u32 D_800FDB9C;', 'extern s32 D_800FDB9C;').replace('(u32) w', 'w')
    assert not _children(text)

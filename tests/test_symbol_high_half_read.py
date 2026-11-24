"""A word global's high halfword read as the variable shifted, not through its address."""
from decomprepair.symbol_high_half_read import FAMILY, variants

ARM = '''extern u32 D_800FDB9C;
extern s32 gSigned;
void f(u8 *p)
{
  u32 *cmd = &D_800FDB9C;
  p[0xC0] = (s8) (*((u16 *) (&D_800FDB9C)));
  p[0xC1] = (s8) (*((s16 *) (((char *) (&gSigned)) + 0)));
  *cmd = 4;
}
'''


def _children(text, arch='mips'):
    return [src for fam, src in variants(text, 'f', None, arch) if fam == FAMILY]


def test_each_read_is_shifted_alone_and_together():
    kids = _children(ARM)
    one = ARM.replace('(*((u16 *) (&D_800FDB9C)))', '((D_800FDB9C >> 16))')
    two = ARM.replace('(*((s16 *) (((char *) (&gSigned)) + 0)))', '(((s16) ((u32) gSigned >> 16)))')
    assert one in kids and two in kids
    assert two.replace('(*((u16 *) (&D_800FDB9C)))', '((D_800FDB9C >> 16))') in kids


def test_only_big_endian_mips():
    assert not _children(ARM, arch='x86')


def test_an_undeclared_symbol_is_left_alone():
    assert not _children(ARM.replace('extern u32 D_800FDB9C;\n', '').replace('extern s32 gSigned;\n', ''))

"""mask_helper_return_width: an inline `& 0xFFFF` helper returning a byte is widened to a halfword."""
from decomprepair import mask_helper_return_width as c

SOURCE = '''u16 next(void);

inline static unsigned char low(u16 arg0)
{
  return arg0 & 0xFFFF;
}

s32 scale(s32 v)
{
  return low(v) * 0x18;
}
'''


def test_the_return_type_becomes_unsigned_short():
    (family, out), = c.variants(SOURCE, 'scale')
    assert family == 'mask_helper_return_width'
    assert 'inline static unsigned short low(u16 arg0)' in out
    assert out.replace('unsigned short low', 'unsigned char low') == SOURCE


def test_a_helper_with_another_mask_or_body_is_left_alone():
    assert c.variants(SOURCE.replace('0xFFFF', '0xFF'), 'scale') == []
    assert c.variants(SOURCE.replace('return arg0 & 0xFFFF;', 'return arg0 & 0xFFFF & next();'), 'scale') == []

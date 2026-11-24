"""A tested command byte, a call's index copy and indexed stores, written together."""
from decomprepair.byte_test_index_split import FAMILY, variants

# A sound-sequence interpreter's indirect-variable write (KMC GCC 2.7.2, N64), m2c's form.
WRITE = '''void f(u8 *arg0)
{
  u32 x;
  s32 o;
  {
    u16 data;
    x = ((u32) W) >> 0x10;
    data = D;
    if ((((u32) W) >> 8) & 0xFF)
    {
      put(arg0, x & 0xFF, data);
    }
    else
    {
      x = x & 0x1F;
      o = x * 2;
      if (x < 0x10U)
      {
        *((u16 *) (((char *) (o + arg0)) + 0x180)) = data;
        return;
      }
      *((s16 *) (((char *) (&G)) + o)) = data;
    }
    break;
  }
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_three_together_first_then_each():
    kids = _children(WRITE)
    assert len(kids) == 4
    whole = kids[0]
    assert '    u8 idx;\n' in whole and '    u8 flag = ((u32) W) >> 8;\n' in whole
    assert '    idx = x;\n    if (flag)\n' in whole and 'put(arg0, idx & 0xFF, data);' in whole
    assert '((u16 *) ((char *) arg0 + 0x180))[x] = data;' in whole and '((s16 *) &G)[x] = data;' in whole
    assert 'o = x * 2;' not in whole


def test_no_index_from_the_same_word_is_left_alone():
    assert _children(WRITE.replace('x = ((u32) W) >> 0x10;', 'x = ((u32) V) >> 0x10;')) == []

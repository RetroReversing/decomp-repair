"""The scaffolding steps of a slot loop as one child."""
from decomprepair import slot_loop_scaffold as p

SOURCE = '''typedef unsigned char u8;
typedef short s16;
extern volatile s16 stamp[4];
extern s16 flags[4];
extern u8 a[16];
extern u8 b[16];
extern s16 last;
extern int slot;
inline static int inline_fn(int arg0)
{
  return -arg0;
}

int f(void)
{
  int i = slot;
  s16 *p = &flags[i];
  *p = 0;
  stamp[i] = 0;
  last = inline_fn(1);
  if (a[i * 4] == 0 && (b[i * 4] & 1) != 0)
  {
    return 1;
  }
  return 0;
}
'''


def test_the_four_steps_come_as_one_child():
    (family, text), = p.variants(SOURCE, 'f')
    assert family == p.FAMILY
    assert 'extern s16 stamp[4];' in text and 'volatile' not in text
    assert 'last = -1;' in text and 'inline_fn' not in text
    assert 's16 *p = (s16 *) (i * 2 + (s32) flags);' in text
    assert 'int i_scaled = i * 4;' in text and 'a[i_scaled]' in text


def test_fewer_than_two_steps_make_no_child():
    only = SOURCE.replace('extern volatile s16 stamp[4];', 'extern s16 stamp[4];').replace('last = inline_fn(1);', 'last = 1;')
    only = only.replace('&flags[i]', 'flags').replace('a[i * 4]', 'a[i * 3]').replace('b[i * 4]', 'b[i]')
    assert p.variants(only, 'f') == []

"""A word local only one case reads as a byte or halfword, declared in that case at that width."""
from decomprepair.case_local_narrow import FAMILY, variants

# A sound-sequence interpreter (KMC GCC 2.7.2, N64): a group-link clamp and a slot command, each with m2c's word local.
SWITCH = '''void f(u8 *v, s32 op)
{
  s32 sum;
  u32 slot;
  register s16 t;
  switch (op)
  {
    case 1:
      sum = v[0x2E] + G;
      t = sum;
      if (t < 0)
      {
        sum = 0;
      }
      link(v, sum & 0xFF);
      break;

    case 2:
      slot = ((u32) W) >> 8;
      v[((slot & 0xFF) * 0xC)] = 0;
      break;

  }
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_halfword_and_byte_locals_move_into_their_cases():
    kids = _children(SWITCH)
    assert len(kids) == 3
    assert '  s32 sum;\n' not in kids[0] and '    case 1:\n    {\n      u16 sum;\n' in kids[0]
    assert '    case 1:\n    {\n      s16 sum;\n' in kids[1]
    assert '    case 2:\n    {\n      u8 slot;\n' in kids[2] and 'v[((slot) * 0xC)] = 0;' in kids[2]
    assert '  u32 slot;\n' not in kids[2]


def test_a_whole_word_read_is_left_alone():
    assert len(_children(SWITCH.replace('link(v, sum & 0xFF);', 'link(v, sum);'))) == 1


def test_a_local_two_cases_use_is_left_alone():
    text = SWITCH.replace('v[((slot & 0xFF) * 0xC)] = 0;', 'v[((slot & 0xFF) * 0xC)] = 0;\n      sum = 1;')
    assert len(_children(text)) == 1

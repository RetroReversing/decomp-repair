"""An inline helper's integer parameter declared at another width."""
from decomprepair.inline_param_width import FAMILY, variants

SRC = '''static inline void branchAtLeast(void *voice, u32 value)
{
  if (value >= G)
  {
    jump(voice);
  }
}

void f(void *v)
{
  branchAtLeast(v, next() & 0xFF);
}
'''


def test_each_other_width_is_offered():
    kids = [src for fam, src in variants(SRC, 'f') if fam == FAMILY]
    assert len(kids) == 4
    assert SRC.replace('u32 value', 'u16 value') in kids and SRC.replace('u32 value', 'u8 value') in kids


def test_pointers_and_the_function_itself_are_left_alone():
    text = SRC.replace('u32 value', 'u8 *value')
    assert [src for fam, src in variants(text, 'f')] == []
    assert [src for fam, src in variants(SRC, 'branchAtLeast')] == []

"""A narrow local's expression moved into the wide local it is copied to."""
from decomprepair.narrow_copy_source_swap import FAMILY, variants

# A sound-sequence interpreter's group-link command (KMC GCC 2.7.2, N64): a byte field plus a halfword, clamped.
ARM = '''void f(u8 *v, u16 *cmd)
{
  register s16 t;
  s32 w;
  t = v[0x2E] + cmd[0];
  w = t;
  if (t >= 0)
  {
    if (t >= 0x100)
    {
      w = 0xFF;
    }
  }
  else
  {
    w = 0;
  }
  link(v, w & 0xFF);
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_wide_local_takes_the_sum_and_the_narrow_one_copies_it():
    assert _children(ARM) == [ARM.replace('  t = v[0x2E] + cmd[0];\n  w = t;\n', '  w = v[0x2E] + cmd[0];\n  t = w;\n')]


def test_two_wide_locals_are_left_alone():
    assert _children(ARM.replace('register s16 t;', 's32 t;')) == []


def test_a_sum_that_names_the_wide_local_is_left_alone():
    assert _children(ARM.replace('cmd[0];\n  w = t;', 'w;\n  w = t;')) == []

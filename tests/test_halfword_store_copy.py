"""A word local stored as halfwords in one arm: a u16 copy before the branch."""
from decomprepair.halfword_store_copy import FAMILY, variants

# A sound-sequence interpreter's variable-write command (KMC GCC 2.7.2, N64).
ARM = '''void f(void *arg0, u32 cmd, u32 i)
{
  s32 value;
  value = G;
  if (cmd & 0xFF)
  {
    put(arg0, i, (s16) value);
  }
  else
  {
    *((u16 *) (((char *) arg0) + 0x180)) = (u16) value;
    *((s16 *) (((char *) (&vars)) + i)) = (s16) value;
  }
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_store_arm_reads_a_u16_copy():
    kids = _children(ARM)
    assert len(kids) == 1
    kid = kids[0]
    assert '  {\n  u16 copy;\n  value = G;\n  copy = value;\n' in kid
    assert '0x180)) = copy;' in kid and 'i)) = copy;' in kid and '(s16) value);' in kid


def test_a_wide_use_in_the_store_arm_leaves_it_alone():
    assert _children(ARM.replace('+ i)) = (s16) value;', '+ i)) = (s16) value;\n    use(value);')) == []


def test_no_halfword_store_leaves_it_alone():
    assert _children(ARM.replace('(u16) value;', 'value;').replace('= (s16) value;', '= value;')) == []

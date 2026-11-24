"""The statement after a calling arm copied into the arm and a new `else`."""
from decomprepair.join_store_else_copy import FAMILY, variants

# A sound-sequence interpreter's pan command (KMC GCC 2.7.2, N64).
ARM = '''void f(void *arg0, u8 t)
{
  u32 *cmd = &G;
  s32 r;
  if (t != 0xFF)
  {
    setSlot(t, *((u8 *) (((char *) arg0) + 0x4B)));
  }
  *cmd = 4;
  r = update(arg0, &G);
  use(r);
}
'''

WANT = '''void f(void *arg0, u8 t)
{
  u32 *cmd = &G;
  s32 r;
  if (t != 0xFF)
  {
    setSlot(t, *((u8 *) (((char *) arg0) + 0x4B)));
    *cmd = 4;
  }
  else
  {
    *cmd = 4;
  }
  r = update(arg0, &G);
  use(r);
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_join_store_is_written_in_both_arms():
    assert _children(ARM) == [WANT]


def test_an_if_with_an_else_is_left_alone():
    text = ARM.replace('  }\n  *cmd = 4;', '  }\n  else\n  {\n    t = 0;\n  }\n  *cmd = 4;')
    assert _children(text) == []


def test_an_arm_without_a_call_is_left_alone():
    assert _children(ARM.replace('setSlot(t, *((u8 *) (((char *) arg0) + 0x4B)));', 't = 1;')) == []


def test_a_statement_with_a_call_is_not_copied():
    assert _children(ARM.replace('*cmd = 4;', '*cmd = next(4);')) == []


def test_an_arm_that_returns_is_left_alone():
    assert _children(ARM.replace('0x4B)));\n  }', '0x4B)));\n    return;\n  }')) == []

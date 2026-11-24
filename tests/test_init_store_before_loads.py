"""A zero store from a record's initialisation run moved ahead of the run's first loads."""
from decomprepair.init_store_before_loads import FAMILY, variants

RUN = '''void f(u8 *arg0)
{
  u8 a;
  if (arg0 != 0)
  {
    a = *((u8 *) (((char *) arg0) + 0xBF));
    *((s32 *) (((char *) arg0) + 0x90)) = 0x64U;
    *((s32 *) (((char *) arg0) + 0x8C)) = 0;
    *((s32 *) (((char *) arg0) + 0x5C)) = 0x4000AC44;
    *((u8 *) (((char *) arg0) + 0xBE)) = a;
  }
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_a_store_moves_ahead_of_the_load():
    moved = RUN.replace('    *((s32 *) (((char *) arg0) + 0x8C)) = 0;\n', '').replace(
        '    a = *((u8', '    *((s32 *) (((char *) arg0) + 0x8C)) = 0;\n    a = *((u8')
    assert moved in _children(RUN)


def test_without_a_load_nothing_moves():
    assert not _children(RUN.replace('    a = *((u8 *) (((char *) arg0) + 0xBF));\n', '    a = 3;\n'))

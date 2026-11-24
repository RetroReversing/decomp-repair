"""A flag word's `&&` chain of bit tests on the local it was read into, nested."""
from decomprepair.field_chain_local_nest import FAMILY, variants

# A sound-sequence interpreter's tick tail (KMC GCC 2.7.2, N64).
TAIL = '''void f(void *arg0)
{
  s32 t;
  t = *((s32 *) (((char *) arg0) + 0x24));
  *((s32 *) (((char *) arg0) + 0xA4)) = *((s32 *) (((char *) arg0) + 0xA4)) + step;
  if ((((*((s32 *) (((char *) arg0) + 0x24))) & 4) && (!(t & 0x40000000))) && ((*((s32 *) (((char *) arg0) + 0x24))) & 8))
  {
    *((s32 *) (((char *) arg0) + 0x24)) = (s32) ((*((s32 *) (((char *) arg0) + 0x24))) & (~4));
    *((s32 *) (((char *) arg0) + 0x9C)) = 0;
  }
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_chain_is_nested_on_the_local_and_the_update_reads_it():
    kids = _children(TAIL)
    assert len(kids) == 1
    kid = kids[0]
    assert '  if ((t) & 4)\n  {\n    if (!(t & 0x40000000))\n    {\n      if ((t) & 8)\n' in kid
    assert '= (t & (~4));' in kid and '+ 0x24))) & 4' not in kid


def test_a_store_to_the_word_in_between_leaves_it_alone():
    text = TAIL.replace('+ 0xA4)) = *((s32 *) (((char *) arg0) + 0xA4)) + step;', '+ 0x24)) = 0;')
    assert _children(text) == []


def test_a_call_in_between_leaves_it_alone():
    text = TAIL.replace('  if ((((', '  g();\n  if ((((', 1)
    assert _children(text) == []

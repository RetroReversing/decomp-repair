"""The mask of a word update held in the local the neighbouring arms keep their result in."""
import re

from decomprepair.rmw_result_local import variants

SOURCE = '''typedef unsigned int u32;
void f(int sel, void *p)
{
  u32 shared;
  u32 t;
  switch (sel)
  {
    case 1:
      t = *((u32 *) (((char *) p) + 0x5C));
      shared = (t & 0xFF81FFFF) | ((((t >> 0x11) & 0x3F) | 4) << 0x11);
      *((u32 *) (((char *) p) + 0x5C)) = shared;
      return;

    case 2:
      t = *((u32 *) (((char *) p) + 0x5C));
      shared = (t & 0xFF81FFFF) | ((((t >> 0x11) & 0x3F) | 8) << 0x11);
      *((u32 *) (((char *) p) + 0x5C)) = shared;
      return;

    case 3:
      t = *((u32 *) (((char *) p) + 0x5C));
      shared = (t & 0xFF81FFFF) | ((((t >> 0x11) & 0x3F) | 2) << 0x11);
      *((u32 *) (((char *) p) + 0x5C)) = shared;
      return;

    case 4:
      t = *((u32 *) (((char *) p) + 0x5C));
      g();
      *((u32 *) (((char *) p) + 0x5C)) = (u32) ((t & 0xFF81FFFF) | ((((t >> 0x11) & 0x3F) | 1) << 0x11));
      return;
  }
}
'''


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def _all(source=SOURCE):
    return [_squash(text) for family, text in variants(source, 'f') if family == 'rmw_result_local']


def test_the_lone_expression_store_gets_its_mask_and_result_in_the_shared_local():
    found = _all()
    assert len(found) == 1
    text = found[0]
    assert 'shared = 0xFF81FFFF; t = *((u32 *) (((char *) p) + 0x5C)); g();' in text
    assert 'shared = t & shared; shared = shared | (((((t >> 0x11) & 0x3F) | 1) << 0x11)); *((u32 *) (((char *) p) + 0x5C)) = shared;' in text


def test_a_function_without_a_shared_local_or_without_an_expression_store_declines():
    few = SOURCE.replace('      shared = (t & 0xFF81FFFF) | ((((t >> 0x11) & 0x3F) | 8) << 0x11);\n', '      shared = 1;\n')
    few = few.replace('      shared = (t & 0xFF81FFFF) | ((((t >> 0x11) & 0x3F) | 2) << 0x11);\n', '')
    assert _all(few) == []
    assert variants(SOURCE, 'missing') == []

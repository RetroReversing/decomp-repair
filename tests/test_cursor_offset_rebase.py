"""cursor_offset_rebase: a cursor started past a record's first element rebased, or element 0 read via the base."""

from decomprepair import cursor_offset_rebase as m

SOURCE = """typedef unsigned short u16;
typedef unsigned char u8;
int g(int, int, int);
void f(u16 *tris, int n)
{
  u16 *p;
  char *q;
  int i;
  p = tris;
  i = 0;
  q = ((char *) p) + 4;
  do
  {
    g(*p, *((u16 *) (((char *) q) + (-2))), *((u16 *) (((char *) q) + 0)));
    q += 6;
    i += 1;
    p += 3;
  }
  while (i < n);
}
"""

BYTES = """typedef unsigned short u16;
typedef unsigned char u8;
int g(int, int, int);
u16 *start(void);
void f(int n)
{
  u16 *p;
  char *q;
  int i;
  p = start();
  i = 0;
  q = ((char *) p) + 2;
  do
  {
    g(*(((u8 *) q) - 2), *((u8 *) (((char *) q) + (-1))), *((u8 *) (((char *) q) + 0)));
    q += 3;
    i += 1;
  }
  while (i < n);
}
"""


def test_the_cursor_is_rebased_to_the_second_element():
    texts = [t for fam, t in m.variants(SOURCE, 'f') if fam == m.FAMILY]
    assert texts
    text = texts[0]
    assert 'q = ((char *) p) + 2;' in text
    assert '(((char *) q) + 0)' in text and '(((char *) q) + 2)' in text and '(-2)' not in text


def test_element_zero_is_read_through_the_base_which_is_retyped_and_stepped():
    [text] = [t for fam, t in m.variants(BYTES, 'f') if fam == m.BASE]
    assert 'u8 *p;' in text and 'p = (u8 *) start();' in text
    assert 'g(*((u8 *) p), ' in text
    assert 'q += 3;\n    p += 3;' in text


def test_a_byte_pointer_start_without_a_cast():
    src = BYTES.replace('u16 *p;', 'unsigned char *p;').replace('p = start();', 'p = (unsigned char *) start();')
    src = src.replace('typedef unsigned char u8;', 'typedef unsigned char u8;\n#define uchar u8').replace(
        'unsigned char *p;', 'u8 *p;').replace('(unsigned char *) start()', '(u8 *) start()').replace(
        'q = ((char *) p) + 2;', 'q = p + 2;')
    [text] = [t for fam, t in m.variants(src, 'f') if fam == m.BASE]
    assert 'g(*((u8 *) p), ' in text and 'q += 3;\n    p += 3;' in text

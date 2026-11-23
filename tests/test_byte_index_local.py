"""A scaled slot index read by several array lookups is kept in a local set after the slot's pointers."""
from decomprepair import byte_index_local as p

SOURCE = '''typedef unsigned char u8;
typedef short s16;
extern u8 a[16];
extern u8 b[16];
extern s16 c[8];
extern int slot;

int f(s16 *flags)
{
  int i = slot;
  s16 *p = flags + i;
  *p = 0;
  if (a[i * 4] == 0 && (b[i * 4] & 1) != 0)
  {
    return c[i * 2];
  }
  return 0;
}
'''


def test_two_lookups_of_one_scale_read_a_local_set_after_the_declarations():
    (family, text), = p.variants(SOURCE, 'f')
    assert family == p.FAMILY
    assert 'int i_scaled = i * 4;' in text
    assert text.index('int i_scaled') > text.index('s16 *p = flags + i;') and text.index('int i_scaled') < text.index('*p = 0;')
    assert 'a[i_scaled]' in text and 'b[i_scaled]' in text
    assert 'c[i * 2]' in text


def test_a_plain_declaration_then_an_assignment_declares_the_local_beside_it():
    source = SOURCE.replace('  int i = slot;\n', '  int i;\n  i = slot;\n')
    (_, text), = p.variants(source, 'f')
    assert 'int i_scaled;\n' in text and 'i_scaled = i * 4;\n' in text
    assert text.index('int i_scaled;') < text.index('i = slot;') + len('i = slot;\n') + 40


def test_a_shift_spelling_counts_as_the_same_scale():
    (_, text), = p.variants(SOURCE.replace('b[i * 4]', 'b[i << 2]'), 'f')
    assert 'b[i_scaled]' in text


def test_an_index_that_changes_or_a_single_lookup_is_left_alone():
    assert p.variants(SOURCE.replace('  *p = 0;\n', '  *p = 0;\n  i = i + 1;\n'), 'f') == []
    assert p.variants(SOURCE.replace('b[i * 4]', 'b[i * 8]'), 'f') == []

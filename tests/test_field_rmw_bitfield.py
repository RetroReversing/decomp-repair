"""m2c's mask-and-shift update of a packed field, written as a bit-field update."""
import re

from decomprepair.field_rmw_bitfield import variants

SOURCE = '''typedef unsigned int u32;
void f(void *p)
{
  u32 t;
  u32 a;
  u32 b;
  t = *((u32 *) (((char *) p) + 0x58));
  *((u32 *) (((char *) p) + 0x58)) = (u32) ((t & 0xFFFF0003) | ((((t >> 2) & 0x3FFF) | 0x10) * 4));
  a = *((u32 *) (((char *) p) + 0x5C));
  b = a & 0xFF81FFFF;
  *((u32 *) (((char *) p) + 0x5C)) = (u32) (b | (((( a >> 0x11) & 0x3F) | 4) << 0x11));
}
'''


def _squash(text):
    return re.sub(r'\s+', ' ', text)


def _all(source=SOURCE, name='f'):
    return [_squash(text) for family, text in variants(source, name) if family == 'field_rmw_bitfield']


def test_a_shifted_multiply_update_becomes_a_field_or():
    found = _all()
    one = [t for t in found if '__repair_bits_58 *) p)->f2 |= 0x10;' in t and '__repair_bits_5C' not in t]
    assert one
    assert 'typedef struct { char pad[0x58]; unsigned int : 16; unsigned int f2 : 14; unsigned int : 2; } __repair_bits_58;' in one[0]
    assert '* 4' not in one[0] and 't = *((u32 *) (((char *) p) + 0x58));' not in one[0]


def test_two_locals_form_and_the_unread_locals_are_dropped():
    found = _all()
    only_5c = [t for t in found if '__repair_bits_5C *) p)->f17 |= 0x4;' in t and '__repair_bits_58' not in t][0]
    assert 'a = *((u32 *)' not in only_5c and 'b = a &' not in only_5c
    assert 'typedef struct { char pad[0x5C]; unsigned int : 9; unsigned int f17 : 6; unsigned int : 17; } __repair_bits_5C;' in only_5c


def test_every_word_at_once_is_offered():
    assert any('__repair_bits_58 *) p)->f2' in t and '__repair_bits_5C *) p)->f17' in t for t in _all())


def test_a_field_that_reaches_the_top_bit_and_two_fields_of_one_word():
    source = '''typedef unsigned int u32;
void f(void *p)
{
  u32 t;
  t = *((u32 *) (((char *) p) + 0x5C));
  *((u32 *) (((char *) p) + 0x5C)) = (u32) ((t & 0x7FFFFF) | (((t >> 0x17) | 8) << 0x17));
  t = *((u32 *) (((char *) p) + 0x5C));
  *((u32 *) (((char *) p) + 0x5C)) = (u32) ((t & 0xFF81FFFF) | ((((t >> 0x11) & 0x3F) | 1) << 0x11));
}
'''
    found = _all(source)
    assert found and 'unsigned int f23 : 9; unsigned int f17 : 6; unsigned int : 17;' in found[0]
    assert '->f23 |= 0x8;' in found[0] and '->f17 |= 0x1;' in found[0]


def test_a_wrong_mask_or_a_constant_wider_than_the_field_declines():
    wrong = SOURCE.replace('0xFFFF0003', '0xFFFF0007')
    assert not [t for t in _all(wrong) if '->f2 |= 0x10;' in t]
    wide = SOURCE.replace('| 0x10) * 4', '| 0x10000) * 4')
    assert not [t for t in _all(wide) if '->f2 |=' in t]


def test_two_different_fields_that_overlap_are_left_alone():
    source = '''typedef unsigned int u32;
void f(void *p)
{
  u32 t;
  t = *((u32 *) (((char *) p) + 0x58));
  *((u32 *) (((char *) p) + 0x58)) = (u32) ((t & 0xFFFF0003) | ((((t >> 2) & 0x3FFF) | 0x10) * 4));
  t = *((u32 *) (((char *) p) + 0x58));
  *((u32 *) (((char *) p) + 0x58)) = (u32) ((t & 0xFFFF0007) | ((((t >> 3) & 0x1FFF) | 0x10) * 8));
}
'''
    assert _all(source) == []


def test_nothing_to_do_for_plain_code():
    assert variants('void f(int *p)\n{\n  *p = 1;\n}\n', 'f') == []
    assert variants(SOURCE, 'missing') == []


JOIN = '''typedef unsigned int u32;
void f(int sel, void *p)
{
  u32 t;
  u32 keep;
  u32 add;
  switch (sel)
  {
    case 1:
      t = (u32) (*((s32 *) (((char *) p) + 0x58)));
      keep = t & 0xFFFF0003;
      add = ((t >> 2) & 0x3FFF) | 0x200;
      goto join;

    case 2:
      g(p);
      t = (u32) (*((s32 *) (((char *) p) + 0x58)));
      keep = t & 0xFFFF0003;
      add = ((t >> 2) & 0x3FFF) | 0x40;
      goto join;

    case 3:
      t = (u32) (*((s32 *) (((char *) p) + 0x58)));
      keep = t & 0xFFFF0003;
      add = ((t >> 2) & 0x3FFF) | 0x10;
      join:
      *((s32 *) (((char *) p) + 0x58)) = (s32) (keep | (add * 4));
      goto after;

    case 4:
      after:
      h(p);
      return;
  }
}
'''


def test_a_join_that_stores_two_locals_each_arm_set_is_written_in_every_arm():
    found = _all(JOIN)
    text = [t for t in found if '__repair_bits_58 *) p)->f2 |= 0x200; goto after;' in t]
    assert text
    text = text[0]
    assert '->f2 |= 0x40; goto after;' in text and '->f2 |= 0x10; goto after;' in text
    assert 'join:' not in text and 'keep =' not in text and 'add =' not in text and 'goto join' not in text
    assert 'g(p);' in text


def test_a_join_with_an_arm_that_is_not_an_update_is_left_alone():
    broken = JOIN.replace('add = ((t >> 2) & 0x3FFF) | 0x40;', 'add = 5;')
    assert [t for t in _all(broken) if 'join:' not in t] == []

"""A masked narrow value compared as unsigned, the way the target does (a voice picker, 1020 -> 820 and 2640 -> 2245)."""
from decomprepair import registry
from decomprepair.masked_compare_unsigned import FAMILY, variants

SOURCE = """extern u8 table[];
extern u16 head;
s32 check(s32 priority, s32 voice)
{
  if ((priority & 0xFF) < (head & 0xFFFF))
  {
    return -1;
  }
  if ((priority & 0xFF) < *((u8 *) (table + voice)))
  {
    return -2;
  }
  if (*((u16 *) (table + voice)) > (priority & 0xFFFF))
  {
    return -3;
  }
  return 0;
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'check', '') if family == FAMILY]


def test_each_compare_gets_its_masked_side_cast_and_one_child_does_them_all():
    first, second, third, everything = children()
    assert 'if (((u32) (priority & 0xFF)) < (head & 0xFFFF))' in first
    assert 'if (((u32) (priority & 0xFF)) < *((u8 *) (table + voice)))' in second
    assert 'if (*((u16 *) (table + voice)) > ((u32) (priority & 0xFFFF)))' in third
    assert everything.count('(u32)') == 3


def test_a_cast_side_a_negative_mask_or_a_plain_int_compare_is_left_alone():
    assert len(children(SOURCE.replace('(priority & 0xFF) < (head', '((u32) (priority & 0xFF)) < (head'))) == 3
    assert len(children(SOURCE.replace('priority & 0xFFFF)', 'priority & 0x1FFFF)'))) == 3
    assert not children('s32 check(s32 a, s32 b)\n{\n  if (a < b)\n  {\n    return 1;\n  }\n  return 0;\n}\n')


def test_equality_and_shifted_compares_are_not_touched():
    source = SOURCE.replace('(priority & 0xFF) < (head & 0xFFFF)', '(priority & 0xFF) == (head & 0xFFFF)')
    assert len(children(source)) == 3
    assert not [t for t in children(SOURCE.replace('< (head & 0xFFFF)', '<< (head & 0xFFFF)')) if '(u32) (priority & 0xFF)) <<' in t]


def test_it_declares_itself_to_the_registry():
    assert any(FAMILY in repair.families for repair in registry.declared())

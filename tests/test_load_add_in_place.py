"""A pointer loaded from a field and offset in one expression, written as a load and an add on the local."""
from decomprepair import registry
from decomprepair.load_add_in_place import EVERY, FAMILY, variants

SOURCE = '''void walk(void *rec, s32 i, s32 big)
{
  void *a = NULL;
  void *b = NULL;
  if (big)
  {
    a = ((u8 *) (*((void **) (((u8 *) rec) + 0x3C)))) + i * 6;
  }
  else
  {
    b = ((u8 *) (*((void **) (((u8 *) rec) + 0x3C)))) + i * 3;
  }
  use(a, b);
}
'''


def test_each_load_and_add_is_two_statements_and_all_of_them_come_as_one_child():
    # 350 and 405 with either arm alone, 340 with both, on a 529-instruction N64 function that started at 360
    found = variants(SOURCE, 'walk')
    assert [family for family, _ in found] == [FAMILY, FAMILY, EVERY]
    one, two, both = (text for _, text in found)
    assert 'a = *((void **) (((u8 *) rec) + 0x3C)); a = (u8 *) a + i * 6;' in one and 'b = ((u8 *) (*' in one
    assert 'b = *((void **) (((u8 *) rec) + 0x3C)); b = (u8 *) b + i * 3;' in two and 'a = ((u8 *) (*' in two
    assert both.count('*((void **) (((u8 *) rec) + 0x3C));') == 2 and '((u8 *) (*' not in both


def test_a_sum_that_names_the_local_or_has_no_load_is_left_alone():
    assert variants(SOURCE.replace('+ i * 6', '+ a'), 'walk')[0][1].count('((u8 *) (*') == 1
    assert variants(SOURCE.replace('(*((void **) (((u8 *) rec) + 0x3C)))', 'rec'), 'walk') == []
    assert variants(SOURCE.replace('))) + i *', '))) - i *'), 'walk') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'load_add_in_place' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'load_add_in_place':
            assert registry.problems(repair) == []

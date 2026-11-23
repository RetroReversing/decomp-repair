"""A loop counter's one-off multiple, written as a local set at the top of the loop body."""
from decomprepair import registry
from decomprepair.loop_scaled_index_local import FAMILY, variants

SOURCE = '''void scan(void)
{
  s32 i;
  s32 j;
  i = 0;
  do
  {
    pad = *(u16 *)((u8 *)&table + i * 8);
    row = (u8 *)&rows + i * 160;
    last = *(u8 *)((u8 *)&rows + i * 160);
    i += 1;
  }
  while (i < 4);
  for (j = 0; j < 3; j++)
  {
    hit = *(u16 *)((u8 *)&other + j * 12);
  }
}
'''


def test_a_product_used_once_becomes_a_local_set_at_the_top_of_the_body():
    # a 417-instruction input handler: the table's address was shared through a register until `i * 8` was a value (6575 -> 5445)
    found = variants(SOURCE, 'scan')
    assert [family for family, _ in found] == [FAMILY] * 2
    for_loop, do_loop = sorted((text for _, text in found), key=lambda text: 'j_x12' not in text)
    assert '    s32 i_x8 = i * 8;\n    pad = *(u16 *)((u8 *)&table + i_x8);' in do_loop
    assert 'i * 160' in do_loop  # used twice: the loop pass already shares it
    assert '    s32 j_x12 = j * 12;\n    hit = *(u16 *)((u8 *)&other + j_x12);' in for_loop


def test_a_loop_with_a_continue_or_a_counter_that_is_not_stepped_is_left_alone():
    assert variants(SOURCE.replace('    i += 1;', '    if (c) continue;\n    i += 1;'), 'scan')[0][1].count('i_x8') == 0
    assert all('i_x8' not in text for _, text in variants(SOURCE.replace('    i += 1;\n', ''), 'scan'))


def test_the_module_declares_itself_to_the_registry():
    assert 'loop_scaled_index_local' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'loop_scaled_index_local':
            assert registry.problems(repair) == []

"""A variable masked inside the expression that overwrites it, written as the mask first."""
from decomprepair import registry
from decomprepair.self_mask_split import FAMILY, variants

SOURCE = '''void filter(void)
{
  s32 v;
  s32 m;
  v = in_x;
  v = ((v & m) << 16) / 76;
  out_x = v;
  v = in_y;
  v = ((v & m) << 16) / 76;
  out_y = v;
}
'''


def test_the_mask_comes_out_as_its_own_statement_on_the_same_variable():
    # two dead-zone filters of an input handler: the masked value stays in the variable's register (905 -> 885)
    found = variants(SOURCE, 'filter')
    assert [family for family, _ in found] == [FAMILY] * 3
    first, second, both = (text for _, text in found)
    assert 'v &= m; v = (v << 16) / 76;' in first and first.count('v &= m;') == 1
    assert second.count('v &= m;') == 1 and second.index('v &= m;') > second.index('out_x')
    assert both.count('v &= m; v = (v << 16) / 76;') == 2 and '((v & m)' not in both


def test_an_expression_that_is_not_the_variables_own_update_is_left_alone():
    assert variants(SOURCE.replace('v = ((v & m)', 'w = ((v & m)'), 'filter') == []
    assert variants(SOURCE.replace('  v = ((v & m) << 16) / 76;\n  out_x', '  if (c) v = ((v & m) << 16) / 76;\n  out_x'), 'filter')[0][1].count('v &=') == 1


def test_the_module_declares_itself_to_the_registry():
    assert 'self_mask_split' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'self_mask_split':
            assert registry.problems(repair) == []

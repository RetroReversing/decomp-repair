"""A variable set to a constant and overwritten under a test, written with the constant as the arm of the negated test."""
from decomprepair import registry
from decomprepair.const_arm_conditional_set import FAMILY, variants

SOURCE = '''void count(void)
{
  s16 n;
  s32 i;
  n = 4;
  if (gFlag != 0) { n = D_801002BA; }
  for (i = 0; i < n; i++) { step(i); }
}
'''


def test_the_constant_set_and_the_conditional_load_become_the_two_arms_of_the_negated_test():
    # the loop count of a 417-instruction input handler: the store after the join and the branch's delay slot were the
    # last rows, 770 -> 0
    (family, text), = variants(SOURCE, 'count')
    assert family == FAMILY
    assert '  if (gFlag == 0) { n = 4; } else { n = D_801002BA; }\n' in text
    assert 'n = 4;\n' not in text.replace('{ n = 4; }', '')


def test_the_if_else_spelling_and_a_braceless_arm_give_the_same_child():
    (_, expected), = variants(SOURCE, 'count')
    spelled = SOURCE.replace('  n = 4;\n  if (gFlag != 0) { n = D_801002BA; }', '  if (gFlag != 0) { n = D_801002BA; } else { n = 4; }')
    assert variants(spelled, 'count') == [(FAMILY, expected)]
    braceless = SOURCE.replace('{ n = D_801002BA; }', 'n = D_801002BA;')
    assert variants(braceless, 'count') == [(FAMILY, expected)]
    (_, bare), = variants(SOURCE.replace('gFlag != 0', 'gFlag'), 'count')
    assert 'if (!(gFlag)) { n = 4; }' in bare or 'if (!gFlag) { n = 4; }' in bare or 'if (gFlag == 0)' in bare


def test_a_set_that_is_not_a_constant_or_not_the_same_variable_is_left_alone():
    assert variants(SOURCE.replace('n = 4;', 'n = m;'), 'count') == []
    assert variants(SOURCE.replace('n = D_801002BA;', 'n = 5;'), 'count') == []
    assert variants(SOURCE.replace('{ n = D_801002BA; }', '{ k = D_801002BA; }'), 'count') == []
    assert variants(SOURCE.replace('  n = 4;\n', '  g();\n'), 'count') == []
    assert variants(SOURCE.replace('gFlag != 0', 'a && b'), 'count') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'const_arm_conditional_set' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'const_arm_conditional_set':
            assert registry.problems(repair) == []

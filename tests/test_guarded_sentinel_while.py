"""A sentinel guard over a do-while with the same test, as the plain while (a chain walk in a voice picker, 2310 -> 1550)."""
from decomprepair import registry
from decomprepair.guarded_sentinel_while import FAMILY, variants

SOURCE = """extern u8 first[];
extern u8 next[];
s32 walk(s32 pos, s32 cur)
{
  s32 idx;
  s32 count = 0;
  idx = first[pos];
  if (idx != 0xFF)
  {
    do
    {
      count += idx;
      idx = next[idx];
    }
    while (idx != 0xFF);
  }
  idx = first[cur];
  if (idx != 0xFF)
    do { count -= idx; idx = next[idx]; } while (idx != 0xFF);
  return count;
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'walk', '') if family == FAMILY]


def test_each_guarded_loop_becomes_a_while_and_one_child_rewrites_both():
    first, second, both = children()
    assert 'while (idx != 0xFF) {\n' in first and 'while (idx != 0xFF);' not in first.split('idx = first[cur]')[0]
    assert 'if (idx != 0xFF)\n    do {' in first
    assert 'while (idx != 0xFF) { count -= idx;' in second and 'if (idx != 0xFF)\n  {\n    do' in second
    assert 'do' not in both and 'if (idx' not in both
    assert both.count('while (idx != 0xFF) {') == 2


def test_the_body_and_the_rest_of_the_function_are_kept():
    both = children()[-1]
    assert '      count += idx;\n      idx = next[idx];\n' in both
    assert both.rstrip().endswith('return count;\n}')


def test_a_different_test_at_the_bottom_is_not_the_same_loop():
    source = SOURCE.replace('while (idx != 0xFF);', 'while (idx != 0xFE);', 1)
    assert len(children(source)) == 1


def test_a_condition_with_a_call_or_an_assignment_is_not_repeated():
    assert not children(SOURCE.replace('idx != 0xFF', 'check(idx) != 0'))
    assert not children(SOURCE.replace('idx != 0xFF', '(idx = idx) != 0xFF'))


def test_an_else_arm_or_a_label_in_the_body_blocks_the_rewrite():
    with_else = SOURCE.replace('  if (idx != 0xFF)\n    do { count -= idx; idx = next[idx]; } while (idx != 0xFF);',
                               '  if (idx != 0xFF)\n    do { count -= idx; idx = next[idx]; } while (idx != 0xFF);\n  else count = 0;')
    assert len(children(with_else)) == 1
    labelled = SOURCE.replace('count += idx;', 'again: count += idx;')
    assert len(children(labelled)) == 1


def test_it_declares_itself_to_the_registry():
    assert any(FAMILY in repair.families for repair in registry.declared())

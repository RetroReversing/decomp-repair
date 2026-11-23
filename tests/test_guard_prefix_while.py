"""guard_prefix_while: `if (P && Q) do { B } while (Q);` as `if (P) { while (Q) { B } }`.

From a 222-instruction stream refill built by IDO 7.1 (0 after this step, 60 before it, a second loop whose guard
repeated its trailing operands at the bottom). Checked on a small function of the same shape, never on game code."""
from decomprepair import registry
from decomprepair.guarded_sentinel_while import FAMILY, PREFIX, variants

SOURCE = """void drain(Ring *p, s32 budget)
{
  if ((p->mode == 3 || p->mode == 4) && p->count <= 0 && p->used < p->size - 0xA0 && budget > 0)
  {
    do
    {
      step(p);
      p->used += 0xA0;
      budget -= 1;
    }
    while (p->used < p->size - 0xA0 && budget > 0);
  }
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'drain', '') if family == PREFIX]


def test_the_leading_operands_stay_in_an_if_and_the_trailing_ones_test_a_while():
    (text,) = children()
    assert 'if ((p->mode == 3 || p->mode == 4) && p->count <= 0) { while (p->used < p->size - 0xA0 && budget > 0) {' in text
    assert 'do' not in text and 'p->used += 0xA0;' in text and text.count('budget -= 1;') == 1


def test_a_guard_equal_to_the_test_is_still_the_plain_sentinel_form():
    source = SOURCE.replace('(p->mode == 3 || p->mode == 4) && p->count <= 0 && ', '')
    assert children(source) == []
    assert [family for family, _ in variants(source, 'drain', '')] == [FAMILY]


def test_a_guard_that_does_not_end_in_the_test_is_left_alone():
    source = SOURCE.replace('p->used < p->size - 0xA0 && budget > 0)\n  {', 'budget > 0 && p->used < p->size - 0xA0)\n  {')
    assert children(source) == []


def test_a_test_with_a_call_is_left_alone():
    source = SOURCE.replace('budget > 0)\n  {', 'more(p) && budget > 0)\n  {').replace('budget > 0);', 'more(p) && budget > 0);')
    assert children(source) == []


def test_an_else_after_the_guard_is_left_alone():
    source = SOURCE.replace('    while (p->used < p->size - 0xA0 && budget > 0);\n  }\n', '    while (p->used < p->size - 0xA0 && budget > 0);\n  }\n  else\n  {\n    budget = 0;\n  }\n')
    assert children(source) == []


def test_it_is_declared_for_the_callers():
    assert PREFIX in {family for r in registry.declared() if r.module == 'guarded_sentinel_while' for family in r.families}

"""The statement both arms of an if/else end with, written once after the test."""
from decomprepair import registry
from decomprepair.common_arm_tail_hoist import FAMILY, variants

SOURCE = '''void step(void)
{
  if (a)
  {
    f();
  }
  else
    if (!(flags & 8))
  {
    word[2] = 1;
    mode = 0;
  }
  else
  {
    mode = 0;
  }
  g();
}
'''


def test_the_common_last_statement_comes_out_after_the_test():
    # the arms of a state machine in a 417-instruction input handler: two `beql` targets, the last 20 (885 -> 0 with
    # the other state machine families)
    (family, text), = variants(SOURCE, 'step')
    assert family == FAMILY
    assert text.count('mode = 0;') == 1 and '    word[2] = 1;\n    }\n    mode = 0;\n    }\n  g();' in text
    assert text.index('word[2] = 1;') < text.index('mode = 0;') < text.index('g();')
    assert text.count('{') == text.count('}')


def test_arms_with_other_endings_or_a_test_that_is_a_whole_body_are_left_alone():
    assert variants(SOURCE.replace('    mode = 0;\n  }\n  g();', '    mode = 1;\n  }\n  g();'), 'step') == []
    assert variants(SOURCE.replace('    word[2] = 1;\n', ''), 'step') == []
    assert variants('void step(void) { while (x) if (a) { f(); m = 0; } else { m = 0; } }', 'step') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'common_arm_tail_hoist' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'common_arm_tail_hoist':
            assert registry.problems(repair) == []


CHAINED = '''void fill(void)
{
    do {
        if (t == 5) {
            if (n == a) {
                x[i] = 1;
                n++;
            } else {
                x[i] = 2;
                n++;
            }
        } else {
            if (n == 0) {
                y[0] = 0;
            } else if (n == a) {
                y[1] = 0;
            } else {
                y[2] = n;
            }
            n++;
        }
        i += 2;
    } while (n < a);
}
'''


def test_a_statement_every_leaf_of_a_nested_chain_ends_with_is_written_once_after_it():
    texts = [text for family, text in variants(CHAINED, 'fill') if family == 'chain_tail_hoist']
    best = min(texts, key=lambda text: text.count('n++;'))
    assert best.count('n++;') == 1
    assert best.index('y[2] = n;') < best.index('n++;') < best.index('i += 2;')
    assert best.count('{') == best.count('}')


def test_a_chain_with_another_ending_or_no_else_is_left_alone():
    assert variants('void f(void) { if (a) { g(); n++; } else if (b) { h(); n++; } else { m++; } }', 'f') == []
    assert variants('void f(void) { if (a) { g(); n++; } else if (b) { h(); n++; } }', 'f') == []

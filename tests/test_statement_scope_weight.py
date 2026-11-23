"""One statement of a loop body wrapped in one-shot scopes: a weight for the index it shares."""
from decomprepair import statement_scope_weight as p

SOURCE = '''typedef short s16;
extern s16 valid[4];
extern s16 loaded[4];
extern int slot;

int f(void)
{
  int i;
  for (;;)
  {
    i = slot;
    valid[i] = 0;
    loaded[i] = 0;
    if (valid[i] == 3)
    {
      slot = 1;
    }
    else
    {
      slot = 2;
    }
    if (i > 7)
    {
      return i;
    }
  }
}
'''


def test_each_if_and_indexed_store_of_the_body_gets_depths_one_to_three():
    children = p.variants(SOURCE, 'f')
    texts = [text for _, text in children]
    assert len(texts) == 2 * 3 + 2 * 3  # two ifs and two indexed stores, three depths each
    assert any('do { if (valid[i] == 3)' in t and '} while (0);' in t for t in texts)
    assert any('do { do { loaded[i] = 0; } while (0); } while (0);' in t for t in texts)
    assert not any('do { slot = 1;' in t for t in texts)  # only the top-level statements of the body


def test_the_else_chain_is_wrapped_whole():
    text = p.variants(SOURCE, 'f')[0][1]
    assert 'do { if (valid[i] == 3)' in text and 'slot = 2;\n    }' in text and '} while (0);' in text


def test_a_statement_with_a_continue_or_a_loop_break_or_a_label_is_left_alone():
    for inner in ('continue;', 'break;', 'again: slot = 3;'):
        source = SOURCE.replace('slot = 1;', inner)
        assert all('do { if (valid[i] == 3)' not in text for _, text in p.variants(source, 'f'))


def test_a_break_inside_a_nested_switch_does_not_count():
    source = SOURCE.replace('slot = 1;', 'switch (i) { case 1: slot = 3; break; default: break; }')
    assert any('do { if (valid[i] == 3)' in text for _, text in p.variants(source, 'f'))


def test_no_loop_means_no_children():
    assert p.variants('int f(int x)\n{\n  if (x)\n  {\n    return 1;\n  }\n  return 0;\n}\n', 'f') == []

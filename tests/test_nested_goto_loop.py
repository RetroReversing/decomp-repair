"""m2c's outermost backward goto loop with nested gotos, written as a real loop."""
import re

from decomprepair import registry
from decomprepair.nested_goto_loop import FAMILY, variants

CODE = '''typedef struct Node { struct Node *next; int *item; } Node;
int touch(int *);

int sweep(Node *list, Node *node, float r)
{
  int hit;
  int *item;
  hit = 0;
  item = list->item;
  loop_3:
  if (r > 0.0f)
  {
    hit |= touch(item);
  }
  for (;;)
  {
    if (hit > 3)
    {
      break;
    }
    hit++;
  }
  {
  if (node != NULL)
  {
    item = node->item;
    node = node->next;
    if (node == NULL)
    {
      if (item == NULL)
      {
        goto done;
      }
      goto loop_3;
    }
  }
  done:
  return hit;
  }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_label_becomes_a_loop_that_ends_after_the_last_goto():
    ((family, child),) = variants(CODE, 'sweep')
    assert family == FAMILY
    text = squash(child)
    assert 'loop_3' not in text
    assert 'item = list->item; for (;;) { if (r > 0.0f)' in text
    assert 'goto done; } continue; } } break; } done: return hit;' in text


def test_a_goto_inside_another_loop_is_left_alone():
    inner = CODE.replace('    hit++;\n', '    hit++;\n    if (hit == 2) { goto loop_3; }\n')
    assert variants(inner, 'sweep') == []


def test_a_break_that_would_bind_to_the_new_loop_is_left_alone():
    loose = CODE.replace('  {\n  if (node != NULL)', '  switch (hit) { case 1: hit = 0; }\n  {\n  if (node != NULL)')
    assert variants(loose, 'sweep')
    bound = CODE.replace('    item = node->item;\n', '    item = node->item;\n    if (item == 0) break;\n')
    assert variants(bound, 'sweep') == []


def test_declared_in_the_registry():
    assert any(repair.module.endswith('nested_goto_loop') for repair in registry.declared())

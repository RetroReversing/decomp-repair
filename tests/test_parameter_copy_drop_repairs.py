"""Pointer parameter copies, and copies in a function with a backward goto."""

POINTERS = '''typedef struct Node { struct Node *next; } Node;
int near(void *, void *);

int sweep(void *arg0, Node *arg1, void *arg2)
{
  void *spE4;
  void *spEC;
  Node *cur;
  int hit;
  spE4 = arg0;
  spEC = arg2;
  hit = 0;
  cur = arg1;
  top:
  if (cur != spE4)
  {
    hit += near(cur, spEC);
  }
  cur = cur->next;
  if (cur != 0)
  {
    goto top;
  }
  return hit;
}
'''


def test_pointer_copies_are_dropped_in_a_function_with_a_backward_goto():
    from decomprepair.parameter_copy_drop_repairs import variants as drops
    children = [text for _, text in drops(POINTERS, 'sweep')]
    both = children[0]
    assert 'spE4' not in both and 'spEC' not in both
    assert 'if (cur != arg0)' in both and 'near(cur, arg2)' in both


def test_a_copy_written_again_under_a_goto_is_kept():
    from decomprepair.parameter_copy_drop_repairs import variants as drops
    rewritten = POINTERS.replace('  cur = cur->next;\n', '  cur = cur->next;\n  spEC = cur;\n')
    assert all('spEC' in text for _, text in drops(rewritten, 'sweep'))

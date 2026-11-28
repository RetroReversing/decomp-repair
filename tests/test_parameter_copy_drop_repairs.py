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


FORWARD = '''void queue(s32 arg0, s32 arg1) {
    s32 var_s0;

    var_s0 = arg0;
    if (var_s0 == 1) {
        var_s0 = 2;
    }
    if (arg1 == 1) {
        goto block_5;
    }
    if (arg1 == 2) {
        stop(var_s0);
block_5:
        arg1 = 0;
    }
    send(var_s0, arg1);
}
'''


def test_a_parameter_modified_under_a_forward_goto_is_modified_itself():
    from decomprepair.parameter_copy_drop_repairs import variants
    (family, candidate), = variants(FORWARD, 'queue')
    assert family == 'parameter_copy_drop'
    assert 'var_s0' not in candidate
    assert 'arg0 = 2;' in candidate and 'stop(arg0);' in candidate and 'send(arg0, arg1);' in candidate


def test_a_goto_back_above_the_copy_still_refuses_a_written_local():
    from decomprepair.parameter_copy_drop_repairs import variants
    backward = FORWARD.replace('    var_s0 = arg0;\n', 'top:\n    ;\n    var_s0 = arg0;\n').replace('goto block_5;', 'goto top;')
    assert 'goto top;' in backward
    assert not variants(backward, 'queue')

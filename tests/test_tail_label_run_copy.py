"""tail_label_run_copy: a labelled run that leaves a void function, written in place of each `goto` to it.

The source below is made up; it has the shape of a 95-instruction angle picker whose four arms set one value and
jump to one call, which the game wrote as a call in every arm."""
from decomprepair import mid_label_run_copy as copy

SOURCE = '''extern s32 f(s32, s32);

void h(s32 k, s32 a, s32 b, s32 *out)
{
  s32 v;
  if (k)
  {
    do
    {
      if (k == 1)
      {
        v = a - b;
        goto call;
      }
    }
    while (0);
    if (k == 2)
    {
      v = b - a;
      goto call;
    }
    if (k == 3)
    {
      v = a + b;
      call:
      *out = f(v, 1);
    }
  }
}
'''


def children(source):
    return [text for family, text in copy.variants(source, 'h') if family == copy.TAIL_FAMILY]


def test_every_goto_gets_the_run_and_a_return():
    text = children(SOURCE)[0]
    assert 'goto call' not in text and 'call:' not in text
    assert text.count('*out = f(v, 1);') == 3 and text.count('return;') == 2


def test_each_goto_is_also_offered_alone():
    assert any(text.count('*out = f(v, 1);') == 2 and 'call:' in text for text in children(SOURCE))


def test_a_run_inside_a_loop_is_left_alone():
    assert not children(SOURCE.replace('if (k == 3)', 'while (k == 3)'))


def test_code_after_the_run_is_left_alone():
    assert not children(SOURCE.replace('    }\n  }\n}', '    }\n    *out = 0;\n  }\n}'))


def test_a_function_with_a_result_is_left_alone():
    assert not children(SOURCE.replace('void h', 's32 h'))


def test_skipped_else_arms_are_no_barrier():
    source = SOURCE.replace('      *out = f(v, 1);\n    }\n', '      *out = f(v, 1);\n    }\n    else\n    {\n      *out = 0;\n    }\n')
    assert children(source)

"""branch_orientation reads every `if` of a long function and offers more than the four smallest swaps."""
from decomprepair.pattern_repairs import variants


def _function(arms):
    cases = '\n'.join(
        f'    case {i}:\n      if (p[{i}] == 0)\n      {{\n        q[{i}] = 0;\n      }}\n      else\n      {{\n'
        f'        q[{i}] = {"p[%d] + " % i * (i + 1)}1;\n      }}\n      break;' for i in range(arms))
    return f'void f(int k, int *p, int *q)\n{{\n  switch (k)\n  {{\n{cases}\n  }}\n}}\n'


def _swapped(text, i):
    return f'if (p[{i}] != 0)' in text and f'if (p[{i}] == 0)' not in text


def test_an_if_past_the_twenty_fourth_is_offered():
    text = _function(30)
    kids = [src for fam, src in variants(text, 'f') if fam == 'branch_orientation']
    assert kids and all(any(_swapped(k, i) for i in range(30)) for k in kids)
    # The arms grow with i, so the smallest pairs come first; a long function still reaches the ninth.
    assert any(_swapped(k, 8) for k in kids)
    assert len(kids) == 12


def test_the_late_branch_of_a_long_function_is_reachable():
    text = _function(34).replace('if (p[33] == 0)', 'if (p[33] == 0)', 1)
    late = text.replace('p[33] + ' * 34, '')
    kids = [src for fam, src in variants(late, 'f') if fam == 'branch_orientation']
    assert any(_swapped(k, 33) for k in kids)

"""A loop's own variable written as one of the function's long-lived locals that is free there."""
from decomprepair.loop_role_rename import FAMILY, variants

# Two table passes of a canonical-code builder (KMC GCC 2.7.2, N64): the sort pass counts with `x`, which the decode
# loop later sets afresh as its window; `i` is the next pass's counter and is set before it is read.
PASSES = '''void f(u32 *t, u32 n)
{
  u32 x;
  u32 i;
  u32 a;
  a = 0;
  for (x = 1; x < 16; x++) {
    if (t[x] == n) {
      a++;
    }
  }
  i = 1;
  do {
    t[i] = a;
    i++;
  } while (i < n);
  x = t[0];
  t[1] = x;
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_sort_counter_becomes_the_next_passs_counter():
    want = PASSES.replace('for (x = 1; x < 16; x++) {\n    if (t[x] == n)', 'for (i = 1; i < 16; i++) {\n    if (t[i] == n)')
    assert want in _children(PASSES)


def test_a_counter_read_after_its_loop_is_left_alone():
    text = PASSES.replace('  x = t[0];\n', '  x += t[0];\n')
    assert not any('for (i = 1; i < 16; i++)' in k for k in _children(text))


def test_a_replacement_whose_value_is_still_needed_is_not_used():
    text = PASSES.replace('  i = 1;\n', '  i = i + 1;\n').replace('  u32 a;\n  a = 0;\n', '  u32 a;\n  i = 0;\n  a = 0;\n')
    assert not any('for (i = 1; i < 16; i++)' in k for k in _children(text))


def test_a_value_carried_around_an_enclosing_loop_is_left_alone():
    text = PASSES.replace('  a = 0;\n  for', '  a = 0;\n  do {\n  t[2] = i;\n  for').replace('  i = 1;\n  do', '  } while (--n);\n  i = 1;\n  do')
    assert not any('for (i = 1; i < 16; i++)' in k for k in _children(text))


def test_goto_and_volatile_decline():
    assert _children(PASSES.replace('  x = t[0];', 'L:\n  x = t[0];\n  if (x) goto L;')) == []
    assert _children(PASSES.replace('  u32 a;', '  volatile u32 a;')) == []

"""A search's fences and join guard regrouped as one child.

Synthetic shape of the mixing function's middle (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): an outer fence round
the whole body, an identical-arm guard on a never-assigned local before a compare, a counter reset ahead of a call, a
call-free identical-arm tail. The exact-judge replay is in decompdecomp's tests (it needs the compiler): the combined
child took the chain's state 100 -> 0 on the 370-instruction function; each step alone stayed at 100 or worse."""
from decomprepair import fence_regroup as m
from decomprepair import registry

SOURCE = '''typedef unsigned short u16;
typedef unsigned int u32;
extern u16 g_limit;
extern u16 g_flag;
extern u16 g_cursor;
extern u16 g_done;
void mix(u16 bound)
{
  u32 spare;
  u32 count;
  u32 step;
  u32 index;
  u32 value;
  if (g_flag != 0)
  {
    settle();
  }
  do
  {
    prepare();
    if (spare)
    {
      count = 0;
      reset(bound);
      step = 0;
      value = g_cursor;
    }
    else
    {
      count = 0;
      reset(bound);
      step = 0;
      value = g_cursor;
    }
    if (value < bound)
    {
      do
      {
        if (count >= g_limit)
        {
          break;
        }
        index = value++;
        emit(index, step);
        count++;
        step += 4;
      }
      while (value < bound);
    }
    if (count || g_done)
    {
      value = 0;
    }
    else
    {
      value = 0;
    }
    flip = g_cursor ^ 1;
    pending = g_done;
  }
  while (0);
  finish(value, pending);
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'mix')
    assert all(family in m.FAMILIES for family, _ in found)
    return found


def test_the_combined_child_does_every_step():
    family, text = texts()[0]
    assert family == 'fence_regroup'
    assert 'if (g_flag)\n    {\n      reset(bound);\n      count = 0;' in text  # a flag tested earlier; the reset after the call
    assert 'if (spare)' not in text
    assert 'if (count || g_done)' not in text  # the call-free tail guard collapsed
    assert text.count('while (0)') == 1
    assert '    do { flip = g_cursor ^ 1; pending = g_done; } while (0);\n  }\n  finish(value, pending);' in text


def test_the_counter_reset_moves_after_the_call_in_both_arms():
    text = next(t for f, t in texts() if f == 'init_after_call')
    assert text.count('reset(bound);\n      count = 0;') == 2
    assert 'count = 0;\n      reset(bound);' not in text


def test_the_inner_loops_break_does_not_keep_the_outer_fence():
    text = next(t for f, t in texts() if f == 'fence_open')
    assert text.count('while (0)') == 1  # only the narrowed fence is left
    assert '    do { flip = g_cursor ^ 1; pending = g_done; } while (0);\n  }\n' in text
    assert '  {\n    prepare();' in text


def test_the_guard_flag_children_name_a_scalar_global_tested_earlier():
    flags = [t for f, t in texts() if f == 'join_guard_flag']
    assert len(flags) == 1
    assert 'if (g_flag)\n    {\n      count = 0;' in flags[0]


def test_a_guard_on_an_assigned_local_is_left_alone():
    assigned = SOURCE.replace('  do\n  {\n    prepare();', '  spare = g_done;\n  do\n  {\n    prepare();')
    assert [t for f, t in texts(assigned) if f == 'join_guard_flag'] == []


def test_a_fence_that_breaks_out_of_itself_is_kept():
    kept = SOURCE.replace('    prepare();\n', '    prepare();\n    if (g_done)\n    {\n      break;\n    }\n', 1)
    for _, text in texts(kept):
        assert 'if (g_done)\n    {\n      break;' in text
        assert 'do\n  {\n    prepare();' in text


def test_a_second_run_over_a_result_adds_nothing_new():
    _, text = texts()[0]
    assert all(t != text for _, t in m.variants(text, 'mix'))


def test_it_declares_itself_to_the_registry():
    assert any(r.module == 'fence_regroup' for r in registry.declared())

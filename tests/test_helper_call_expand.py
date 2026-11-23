"""A call to a one-expression `inline` helper written as the expression.

Synthetic shape of the mixing function's three loops (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`): two loops carry the
test, the third calls the helper. The exact-judge replay is in decompdecomp's tests (it needs the compiler): the written-out
test took 515 -> 190 in the chain's state."""
from decomprepair import helper_call_expand as m
from decomprepair import registry

SOURCE = '''typedef unsigned char u8;
extern u8 g_active;
extern int g_tick;
extern int g_reload;
inline static int due(u8 arg0, int arg1)
{
  return (arg0 != 0) && ((--g_tick) == arg1);
}
inline static int twice(int arg0)
{
  return arg0 + arg0;
}
void run(int n)
{
  if ((g_active != 0) && ((--g_tick) == 0))
  {
    g_tick = g_reload;
  }
  if (due(g_active, 0))
  {
    g_tick = twice(n);
  }
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'run')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_call_becomes_the_helpers_expression():
    [text] = texts()
    assert 'if (((g_active != 0) && ((--g_tick) == 0)))' in text
    assert 'due(g_active, 0)' not in text
    assert 'inline static int due' in text  # the helper stays declared


def test_a_helper_that_reads_a_parameter_twice_is_not_expanded():
    assert all('g_tick = (n + n)' not in t for t in texts())


def test_a_call_with_a_compound_argument_is_left_alone():
    assert texts(SOURCE.replace('due(g_active, 0)', 'due(g_active, g_reload + 1)')) == []


def test_it_declares_itself_to_the_registry():
    assert any(r.module == 'helper_call_expand' for r in registry.declared())

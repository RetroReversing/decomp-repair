"""Two locals that always hold one value, their reads assigned between them."""
from decomprepair import copy_pair_read_switch as t

SOURCE = '''void f(s32 n)
{
  f32 w;
  f32 x;
  w = 160.0f;
  x = w;
  g();
  if (n == 2)
  {
    w = (x = 80.0f);
  }
  else
  {
    x = 70.0f;
    h(1);
    w = x;
  }
  use(2.0f * w);
  use(2.0f * x);
  use(2.0f * w);
}
'''


def test_every_assignment_of_the_reads_is_offered():
    # An effect spawner's screen size kept twice (KMC GCC 2.7.2): the right names at its reads, both pairs at once,
    # 85 -> 80; single switches were each worse.
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert len(out) == 7  # 2**3 assignments of the three reads, less the source's own
    assert any('use(2.0f * x);\n  use(2.0f * x);\n  use(2.0f * x);' in o for o in out)
    assert all('w = (x = 80.0f);' in o and 'x = w;' in o for o in out)


def test_left_alone_when_the_two_can_differ():
    apart = SOURCE.replace('    w = x;\n', '    w = x + 1.0f;\n')
    assert t.variants(apart, 'f') == []
    read_between = SOURCE.replace('    h(1);\n', '    h(w);\n')
    assert t.variants(read_between, 'f') == []
    jump_between = SOURCE.replace('    h(1);\n', '    if (n) h(1);\n')
    assert t.variants(jump_between, 'f') == []
    address = SOURCE.replace('  g();', '  g(&w);')
    assert t.variants(address, 'f') == []


def test_it_declares_itself():
    from decomprepair import registry
    assert any(r.module == 'copy_pair_read_switch' for r in registry.declared())

"""zero_guard_while: m2c's guard on a register it knew held zero, before a counted `do`, as a `while`."""

from decomprepair import zero_guard_while as m

SOURCE = """void use(s32);
void f(u16 *base, u16 n, s32 flag)
{
  s32 i;
  u16 *p;
  if (flag == 0)
  {
    if (flag < n)
    {
      i = 0;
      p = base + 2;
      do
      {
        use(*p);
        p += 3;
        i += 1;
      }
      while (((u32) (i & 0xFFFF)) < n);
    }
  }
}
"""


def test_the_counter_is_zeroed_before_the_guard_and_the_do_becomes_a_while():
    children = dict(m.variants(SOURCE, 'f'))
    text = children[m.FAMILY]
    assert text.index('i = 0;') < text.index('if (flag < n)') < text.index('p = base + 2;')
    assert 'while (((u32) (i & 0xFFFF)) < n)\n' in text and 'do' not in text.split('{', 1)[1]


def test_the_unguarded_child_drops_the_guard():
    text = dict(m.variants(SOURCE, 'f'))[m.UNGUARDED]
    assert 'if (flag < n)' not in text and text.index('i = 0;') < text.index('p = base + 2;')
    assert text.count('while (') == 1


def test_a_guard_on_the_counter_itself_is_left_to_guarded_do_for():
    assert m.variants(SOURCE.replace('if (flag < n)', 'if (i < n)'), 'f') == []


def test_a_different_bound_or_a_continue_is_left_alone():
    assert m.variants(SOURCE.replace('if (flag < n)', 'if (flag < 4)'), 'f') == []
    assert m.variants(SOURCE.replace('use(*p);', 'if (*p) continue;'), 'f') == []

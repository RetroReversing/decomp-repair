"""A guarded `do { } while` counted loop, written as the `for` it compiled from."""
from decomprepair import registry
from decomprepair.guarded_do_to_for import FAMILY, variants

SOURCE = '''void poll(void)
{
  s16 n;
  n = 4;
  if ((s16)n > 0)
  {
    s32 p;
    p = 0;
    do
    {
      step(p);
      mark(p * 2);
      p += 1;
    }
    while (p < (s16)n);
  }
}
'''


def test_the_guard_and_the_do_loop_become_a_for():
    # a 417-instruction input handler: only the frame and the stack rows differed until the loop was the `for` (840 -> 770)
    (family, text), = variants(SOURCE, 'poll')
    assert family == FAMILY
    assert 'for (p = 0; p < (s16)n; p++)' in text
    assert 'do' not in text and 'while' not in text and 'if (' not in text
    assert '    s32 p;\n' in text and '      step(p);\n      mark(p * 2);\n' in text and 'p += 1' not in text


def test_the_other_spellings_of_the_guard_and_the_step():
    assert variants(SOURCE.replace('(s16)n > 0', '0 < (s16)n'), 'poll')
    (_, text), = variants(SOURCE.replace('p += 1;', 'p++;'), 'poll')
    assert 'p++)' in text and 'p++;' not in text
    (_, text), = variants(SOURCE.replace('p += 1;', '++p;'), 'poll')
    assert '++p;' not in text


def test_a_loop_the_for_would_change_is_left_alone():
    assert variants(SOURCE.replace('      mark(p * 2);', '      if (p) continue;'), 'poll') == []
    assert variants(SOURCE.replace('p = 0;', 'p = 1;'), 'poll') == []
    assert variants(SOURCE.replace('while (p < (s16)n)', 'while (p < m)'), 'poll') == []
    assert variants(SOURCE.replace('  }\n}', '  }\n  else\n  {\n    z();\n  }\n}'), 'poll') == []
    assert variants(SOURCE.replace('(s16)n > 0', 'n != 0'), 'poll') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'guarded_do_to_for' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'guarded_do_to_for':
            assert registry.problems(repair) == []


TWO = '''inline static u32 widen(s16 arg0)
{
  return (u32) arg0;
}

void fill(s32 *out, s16 *count, s32 n)
{
  s32 i;
  i = 0;
  if (n > 0)
  {
    do
    {
      out[i] = 1;
      i += 1;
    }
    while (i < n);
  }
  if (((s32) (widen((s32) *count) >> 2)) > 0)
  {
    i = 0;
    do
    {
      out[i] = 0;
      i += 1;
    }
    while (i < ((s32) (widen(*count) >> 2)));
  }
}
'''


def test_a_counter_set_before_the_guard_and_bounds_that_differ_by_casts_and_a_cast_helper():
    # a 392-instruction object initialiser: each `for` adds an 8-byte stale frame slot; 22 -> 0 only with both
    texts = [text for _, text in variants(TWO, 'fill')]
    first, second, helper, both, both_helper = texts
    assert 'for (i = 0; i < n; i++)' in first and 'i = 0;\n  if (n > 0)' not in first and 'while (i < ((s32)' in first
    assert 'for (i = 0; i < ((s32) (widen(*count) >> 2)); i++)' in second
    assert 'for (i = 0; i < ((s32) (((u32) (s16) (*count)) / 4)); i++)' in helper
    assert 'do' not in both.split('fill', 1)[1] and 'widen(*count)' in both
    assert 'for (i = 0; i < n; i++)' in both_helper and '/ 4)); i++)' in both_helper and 'do\n' not in both_helper

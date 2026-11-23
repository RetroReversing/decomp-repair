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

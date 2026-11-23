"""A `for` loop that steps pointers started just before it, written as the guarded `do { } while`."""
from decomprepair import registry
from decomprepair.guarded_cursor_do_loop import FAMILY, variants

SOURCE = '''void walk(s32 n)
{
  s32 i;
  if (n > 0)
  {
    f32 *y = (f32 *)((u8 *)&D_80100018 + 4);
    f32 *x = &D_80100018;
    for (i = 0; i < n; y += 9, i++, x += 9)
    {
      if (*x < D_80100000)
      {
        D_80100000 = *x;
      }
      if (*y > D_80100004)
      {
        D_80100004 = *y;
      }
    }
    D_80100008 = 1;
  }
}
'''


def test_the_starts_move_into_the_guard_and_the_steps_to_the_end_of_a_do_loop():
    # a 529-instruction N64 function: the order of the entry's instructions was the only difference left (120 -> 0)
    (family, text), = variants(SOURCE, 'walk')
    assert family == FAMILY
    assert '    f32 *y;\n    f32 *x;\n' in text and 'for' not in text
    guard = text.index('i = 0;\n    if (i < n)')
    assert guard < text.index('y = (f32 *)((u8 *)&D_80100018 + 4);') < text.index('x = &D_80100018;') < text.index('do')
    assert 'y += 9; i++; x += 9;' in text and '} while (i < n);' in text
    assert text.index('} while (i < n);') < text.index('D_80100008 = 1;')


def test_a_loop_with_a_continue_a_step_that_is_not_a_cursor_or_no_starts_is_left_alone():
    assert variants(SOURCE.replace('      if (*y >', '      if (c) continue;\n      if (*y >'), 'walk') == []
    assert variants(SOURCE.replace('x += 9', 'x = g(x)'), 'walk') == []
    assert variants(SOURCE.replace('    f32 *x = &D_80100018;\n', ''), 'walk') == []
    assert variants(SOURCE.replace('i = 0; i < n;', 'i = 1; i < n;'), 'walk') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'guarded_cursor_do_loop' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'guarded_cursor_do_loop':
            assert registry.problems(repair) == []

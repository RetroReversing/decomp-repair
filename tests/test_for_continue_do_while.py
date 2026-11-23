"""An outer for loop with continues and an inner loop, as a guarded do-while (a collision query, 350 -> 0)."""
from decomprepair.for_continue_do_while import FAMILY, variants

SOURCE = """void walk(Obj *obj, s32 n)
{
  u16 j;

  for (; obj != NULL; obj = obj->next)
  {
    if (!(obj->flags & 0x200)) continue;
    for (j = 0; j < n; j++)
    {
      if (j == 3) continue;
      use(obj, j);
    }
  }
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'walk') if family == FAMILY]


def test_the_walk_becomes_a_guarded_do_while_and_its_own_continue_a_goto():
    (child,) = children()
    assert '  if (obj != NULL)\n  {\n  do\n  {' in child
    assert 'if (!(obj->flags & 0x200)) goto next_obj;' in child
    assert 'if (j == 3) continue;' in child
    assert '  next_obj:\n    obj = obj->next;\n  }\n  while (obj != NULL);\n  }' in child


def test_a_loop_without_an_inner_loop_is_left_alone():
    source = SOURCE.replace('    for (j = 0; j < n; j++)\n    {\n      if (j == 3) continue;\n      use(obj, j);\n    }\n',
                            '    use(obj, 0);\n')
    assert not children(source)


def test_an_initialiser_is_kept_before_the_guard():
    (child,) = children(SOURCE.replace('for (; obj != NULL;', 'for (obj = first(); obj != NULL;'))
    assert child.index('obj = first();') < child.index('if (obj != NULL)')


def test_a_call_in_the_test_or_step_is_not_repeated():
    assert not children(SOURCE.replace('obj = obj->next)', 'obj = after(obj))'))

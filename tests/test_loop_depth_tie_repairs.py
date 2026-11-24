"""A do/while as m2c's goto loop, and a parameter's read in a one-shot scope (loop-depth weight)."""
from decomprepair import registry
from decomprepair.loop_depth_tie_repairs import GOTO_LOOP, PARAM_SCOPE, variants

CODE = '''typedef unsigned short u16;
typedef float f32;
typedef int s32;

s32 clampAll(f32 *v, u16 n, f32 lo, f32 hi)
{
  u16 i;
  f32 t;
  f32 x;
  i = 0;
  do
  {
    x = v[i];
    t = x - lo; if (t > x) { v[i] = t; }
    t = x + hi; if (t < x) { v[i] = t; }
    i += 1;
  } while (i < n);
  do { } while (0);
  return i;
}
'''


def test_a_do_while_is_written_as_a_goto_loop():
    loops = [t for f, t in variants(CODE, 'clampAll') if f == GOTO_LOOP]
    assert len(loops) == 1
    assert 'loop_0: {' in loops[0] and '} if (i < n) { goto loop_0; }' in loops[0]
    assert 'do { } while (0);' in loops[0]


def test_a_loop_with_a_break_is_left_alone():
    assert not [t for f, t in variants(CODE.replace('i += 1;', 'if (i == 9) break; i += 1;'), 'clampAll')
                if f == GOTO_LOOP]


def test_a_parameter_read_gets_a_one_shot_scope_with_its_if():
    scopes = [t for f, t in variants(CODE, 'clampAll') if f == PARAM_SCOPE]
    assert any('do { t = x + hi; if (t < x) { v[i] = t; } } while (0);' in t for t in scopes)
    assert any('do { t = x - lo; if (t > x) { v[i] = t; } } while (0);' in t for t in scopes)


def test_the_goto_loop_is_offered_with_the_float_parameter_scopes():
    both = [t for _, t in variants(CODE, 'clampAll')
            if 'goto loop_0;' in t and 'do { t = x + hi; if (t < x) { v[i] = t; } } while (0);' in t]
    assert both


def test_the_module_declares_itself():
    assert 'loop_depth_tie_repairs' in {repair.module.rsplit('.', 1)[-1] for repair in registry.declared()}

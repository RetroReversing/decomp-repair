"""A command loop's skipped result copy given a word result and a byte flag, and an arm that sets the flag itself."""
from decomprepair.join_skip_width_conflict import FAMILY, variants

# A sound-sequence interpreter's command loop (KMC GCC 2.7.2, N64), cut down.
LOOP = '''void f(Seq *s)
{
  s32 t;
  u8 result;
  s32 done;
  do {
    switch (s->op)
    {
      case 0x1:
        if (s->on && ((t = s->x, result = 0, t != 0)))
      {
        s->pc = t;
      }
      else
      {
        goto release;
      }
        break;

      case 0x2:
        result = step(s);
        break;

      default:
        done = 0;
        goto command_test;
    }
    done = result;
    command_test:

    if (done & 0xFF)
      break;
  } while (++s->n < 0x21);
  return;
  release:
  stop(s);
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_result_widens_and_the_flag_narrows():
    typed = LOOP.replace('  u8 result;\n', '  s32 result;\n').replace('  s32 done;\n', '  u8 done;\n')
    assert typed in _children(LOOP)


def test_the_arm_sets_the_flag_and_goes_to_the_test():
    typed = LOOP.replace('  u8 result;\n', '  s32 result;\n').replace('  s32 done;\n', '  u8 done;\n')
    arm = typed.replace('result = 0, t != 0', 'done = 0, t != 0').replace(
        '        s->pc = t;\n      }\n      else\n      {\n        goto release;\n      }\n        break;\n',
        '        s->pc = t;\n        goto command_test;\n      }\n      else\n      {\n        goto release;\n      }\n')
    assert arm in _children(LOOP)


def test_without_the_skip_nothing_is_offered():
    plain = LOOP.replace('        done = 0;\n        goto command_test;\n', '        result = 0;\n')
    assert not _children(plain)


def test_already_wide_and_narrow_is_left_alone():
    typed = LOOP.replace('  u8 result;\n', '  s32 result;\n').replace('  s32 done;\n', '  u8 done;\n')
    assert not _children(typed)

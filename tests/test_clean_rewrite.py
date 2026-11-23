"""clean_rewrite: a scaffolded m2c saved best written back as plain C, one rule at a time, each checked by running it."""
import shutil
import subprocess

import pytest

from decomprepair import clean_rewrite as c
from decomprepair import registry

TYPES = 'typedef int s32; typedef unsigned int u32; typedef short s16; typedef unsigned short u16; ' \
        'typedef signed char s8; typedef unsigned char u8;\n'


def run(tmp_path, source, calls):
    """stdout of a host program printing each call of `calls` (the same values for every rewrite of one function)."""
    main = 'int printf(const char *, ...);\nint main(void) {\n' + ''.join(
        f'  printf("%d\\n", (int) {call});\n' for call in calls) + '  return 0;\n}\n'
    (tmp_path / 't.c').write_text(TYPES + source + '\n' + main)
    subprocess.run(['cc', '-w', '-o', str(tmp_path / 't'), str(tmp_path / 't.c')], check=True)
    return subprocess.run([str(tmp_path / 't')], capture_output=True, text=True, check=True).stdout


host = pytest.mark.skipif(shutil.which('cc') is None, reason='no host C compiler')

BACK_LOOP = """s32 sum(s32 *p, s32 n)
{
  s32 i;
  s32 total;
  i = 0;
  total = 0;
loop_1:
  total += p[i];
  i += 1;
  if (i < n) goto loop_1;
  return total;
}
"""


def test_backward_goto_is_a_do_while():
    text = c.structure(BACK_LOOP, 'sum')
    assert 'goto' not in text and 'loop_1' not in text
    assert '  do\n  {' in text and '} while (i < n);' in text


FORWARD = """s32 pick(s32 a, s32 b)
{
  s32 r;
  r = a;
  if (a >= b) goto block_3;
  r = b * 2;
  r += 1;
block_3:
  r -= 1;
  return r;
}
"""


def test_forward_goto_is_an_if():
    text = c.structure(FORWARD, 'pick')
    assert 'goto' not in text and 'if (a < b)' in text


def test_else_arm_goto_is_left_alone():
    source = FORWARD.replace('  if (a >= b) goto block_3;', '  if (a) r = 1;\n  else if (a >= b) goto block_3;')
    text = c.structure(source, 'pick') or source
    assert 'if (a < b)' not in text  # wrapping the rest in the else arm's `if` would change what runs


def test_loop_with_its_own_break_is_declined():
    source = BACK_LOOP.replace('  total += p[i];', '  total += p[i];\n  if (total > 99) break;')
    source = source.replace('{\n  s32 i;', '{\n  s32 i;\n  for (;;) {', 1).replace('  return total;', '  }\n  return total;')
    text = c.structure(source, 'sum') or source
    assert 'goto loop_1;' in text


SWITCH = """s32 code(s32 k)
{
  s32 r;
  r = 0;
  switch (k)
  {
    case 1:
      r = 10;
      goto block_9;
    case 2:
      r = 20;
      goto block_9;
    default:
      r = 30;
  }
block_9:
  return r + 1;
}
"""


def test_goto_after_switch_is_break():
    text = c.structure(SWITCH, 'code')
    assert 'goto' not in text and text.count('break;') == 2


GUARDED = """s32 count(s32 n)
{
  s32 i;
  i = 0;
  if (i < n)
  {
    do
    {
      i += 1;
    }
    while (i < n);
  }
  return i;
}
"""


def test_guarded_do_while_is_a_while():
    text = c.structure(GUARDED, 'count')
    assert 'while (i < n)\n  {' in text and 'do' not in text


HELPERS = """inline static s32 *inline_fn(char *arg0)
{
  return (s32 *) arg0;
}

inline static int inline_fn2(s32 arg0, s32 arg1)
{
  return arg0 + arg1;
}

s32 helpers(s32 *p, s32 x)
{
  *inline_fn(((char *) p) + 4) = inline_fn2(x, inline_fn2(x, 3));
  return p[1];
}
"""


def test_identity_helpers_are_inlined():
    text = c.scaffold(HELPERS, 'helpers')
    assert 'inline_fn' not in text
    assert '((s32 *) (((char *) p) + 4))' in text


def test_narrow_parameter_helper_is_kept():
    source = HELPERS.replace('inline_fn2(s32 arg0', 'inline_fn2(u8 arg0')
    text = c.scaffold(source, 'helpers') or source
    assert 'inline_fn2(' in text  # the call truncates its argument: inlining would not


def test_twice_read_parameter_needs_a_pure_argument():
    source = HELPERS.replace('return arg0 + arg1;', 'return arg0 + arg0 + arg1;').replace(
        'inline_fn2(x, inline_fn2(x, 3))', 'inline_fn2(p[0]++, 3)')
    text = c.scaffold(source, 'helpers') or source
    assert 'inline_fn2(p[0]++, 3)' in text


FIELDS = """typedef struct
{
  unsigned char pad[8];
  int value;
} __repair_field_8;

s32 field(void *p)
{
  s32 __repair_literal;
  s32 __repair_phase_x;
  __repair_literal = 2;
  __repair_phase_x = ((__repair_field_8 *) p)->value;
  return __repair_phase_x * __repair_literal;
}
"""


def test_field_views_literals_and_phase_names():
    text = c.plain(c.scaffold(FIELDS, 'field'), 'field')
    assert '__repair_' not in text
    assert '(*((int *) ((char *) p + 8)))' in text and '* 2' in text


DEREF = """s32 deref(void *arg0)
{
  return (*((s32 *) (((char *) arg0) + 0x10))) + (*((u8 *) (((char *) arg0) + 0)));
}
"""


def test_deref_spelling():
    text = c.spelling(DEREF, 'deref')
    assert '*(s32 *)((char *)arg0 + 0x10)' in text and '*(u8 *)arg0' in text


def test_levels_and_registry():
    source = HELPERS.replace('  return p[1];', '  x = *((s32 *) (((char *) p) + 8));\n  do\n  {\n    x += 2;\n  } while (0);\nloop_1:\n  x += 1;\n  if (x < 3) goto loop_1;\n  return p[1] + x;')
    families = [family for family, _ in c.variants(source, 'helpers')]
    assert families == [c.STRUCTURE, c.SCAFFOLD, c.FAMILY]
    repair = registry.get('clean_rewrite')
    assert repair and not registry.problems(repair)
    assert c.variants('void f(void) { }', 'f') == []


@host
@pytest.mark.parametrize('source,name,calls', [
    (BACK_LOOP, 'sum', ['sum(data, 1)', 'sum(data, 4)']),
    (FORWARD, 'pick', ['pick(1, 2)', 'pick(5, 2)', 'pick(3, 3)']),
    (SWITCH, 'code', ['code(1)', 'code(2)', 'code(7)']),
    (GUARDED, 'count', ['count(0)', 'count(5)']),
    (HELPERS, 'helpers', ['helpers(data, 3)']),
    (FIELDS, 'field', ['field(data)']),
    (DEREF, 'deref', ['deref(data)']),
])
def test_every_level_runs_the_same(tmp_path, source, name, calls):
    prelude = 's32 data[8] = {1, 2, 3, 4, 5, 6, 7, 8};\n'
    expected = run(tmp_path, prelude + source, calls)
    found = c.variants(source, name)
    assert found
    for _, text in found:
        assert run(tmp_path, prelude + text, calls) == expected

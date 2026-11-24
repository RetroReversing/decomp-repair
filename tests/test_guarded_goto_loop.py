"""A backward goto loop with a guarded test and a switch in its body, written as a `do { } while`.

Synthetic shape of a sound-sequence interpreter's command loop (KMC GCC 2.7.2); on the 1315-instruction interpreter
the loop with its cached `-1` written as a literal went 22323 -> 19185 (exact judge, decompdecomp's tests)."""
from decomprepair import guarded_goto_loop as m
from decomprepair import registry

SOURCE = '''typedef unsigned char u8;
typedef int s32;
extern u8 gCount;
extern s32 gCmd;
s32 handle(s32);

void run(s32 *voice)
{
  s32 result;
  s32 invalid;
  u8 next;
  gCount = 1;
  invalid = -1;
  loop_25:
  switch (gCmd & 0x7F)
  {
    case 1:
      result = handle(gCmd);
      break;
    case 2:
      if (voice[1] != invalid)
      {
        result = 0;
        break;
      }
      result = 1;
      break;
  }
  if (!(result & 0xFF))
  {
    next = gCount + 1;
    gCount = next;
    if (((s32) (next & 0xFF)) < 0x21)
    {
      goto loop_25;
    }
  }
  voice[2] += 1;
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'run')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_guard_becomes_a_break_and_the_test_the_loop_condition():
    loop, literal = texts()
    assert 'loop_25' not in loop
    assert 'do {' in loop and 'if (result & 0xFF)\n      break;' in loop
    assert '} while (((s32) (next & 0xFF)) < 0x21);\n  voice[2] += 1;' in loop
    assert 'invalid = -1;' in loop
    # the cached literal written where the loop reads it, its declaration gone
    assert 'invalid' not in literal and 'voice[1] != (-1)' in literal and 'do {' in literal


def test_a_plain_backward_test_without_a_guard():
    source = SOURCE.replace('''  if (!(result & 0xFF))
  {
    next = gCount + 1;
    gCount = next;
    if (((s32) (next & 0xFF)) < 0x21)
    {
      goto loop_25;
    }
  }''', '''  if (result == 0)
    goto loop_25;''')
    loop = texts(source)[0]
    assert '} while (result == 0);' in loop and 'break;\n' not in loop.split('}\n  if')[0][-20:]


def test_a_break_that_would_leave_the_loop_is_left_alone():
    source = SOURCE.replace('  if (!(result & 0xFF))\n  {', '  if (result == 5) result = 6;\n  if (!(result & 0xFF))\n  {\n    if (result == 7) break;')
    assert texts(source) == []


def test_it_declares_itself():
    repair = next(r for r in registry.declared() if r.module == 'guarded_goto_loop')
    assert registry.problems(repair) == []

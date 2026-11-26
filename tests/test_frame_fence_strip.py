"""Address-taking fences and dead `if (0) goto` ladders, written out so the frame shrinks."""
import re

from decomprepair import registry
from decomprepair.frame_fence_strip import FAMILIES, FAMILY, FAMILY_ADDRESS, FAMILY_GOTO, variants

CODE = '''extern char tab[];
void send(s32 a, s32 b);

void wrap(s32 arg0, s16 arg1)
{
  s32 temp_v0;
  (void) (&temp_v0);
  loop_goto_1:
  {
    temp_v0 = (arg0 & 0xFF) * 0xC;
  }
  if (0)
  {
      goto loop_goto_1;
  }
  send(*((u16 *) (tab + temp_v0)), arg1);
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text).strip()


def test_both_scaffolds_come_first_then_each_alone():
    out = variants(CODE, 'wrap')
    assert [f for f, _ in out] == [FAMILY, FAMILY_ADDRESS, FAMILY_GOTO]
    both, address, jump = (squash(t) for _, t in out)
    assert both == squash('''extern char tab[]; void send(s32 a, s32 b);
void wrap(s32 arg0, s16 arg1) { s32 temp_v0; temp_v0 = (arg0 & 0xFF) * 0xC;
send(*((u16 *) (tab + temp_v0)), arg1); }''')
    assert '(void)' not in address and 'loop_goto_1:' in address and 'if (0)' in address
    assert '(void)' in jump and 'loop_goto_1' not in jump


def test_the_unbraced_form_and_other_dead_tests_go_too():
    code = CODE.replace('''if (0)
  {
      goto loop_goto_1;
  }''', 'if (0 != 0) goto loop_goto_1;').replace('(void) (&temp_v0);', '(void)&temp_v0;')
    both = squash(variants(code, 'wrap')[0][1])
    assert '(void)' not in both and 'goto' not in both and 'loop_goto_1' not in both


def test_a_label_a_live_goto_still_reaches_stays():
    code = CODE.replace('send(', 'if (arg1) goto loop_goto_1;\n  send(')
    jump = squash(dict(variants(code, 'wrap'))[FAMILY_GOTO])
    assert 'loop_goto_1:' in jump and 'goto loop_goto_1;' in jump and 'if (0)' not in jump


def test_a_block_that_declares_something_is_not_opened():
    code = CODE.replace('temp_v0 = (arg0 & 0xFF) * 0xC;', 's32 t = 1;\n    temp_v0 = (arg0 & 0xFF) * 0xC + t;')
    jump = squash(dict(variants(code, 'wrap'))[FAMILY_GOTO])
    assert 'loop_goto_1' not in jump and '{ s32 t = 1;' in jump


def test_a_function_with_neither_gets_nothing():
    assert variants('void f(void)\n{\n  g();\n}\n', 'f') == []


def test_it_is_declared_for_every_caller():
    declared = {repair.module: repair for repair in registry.declared()}
    assert set(declared['frame_fence_strip'].families) == set(FAMILIES)

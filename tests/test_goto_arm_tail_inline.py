"""A `goto` to the tail of another switch arm, written as the statements it would run."""
from decomprepair import registry
from decomprepair.goto_arm_tail_inline import FAMILY, variants

SOURCE = '''void step(void)
{
  switch (state)
  {
    default:
      if (a) { next = 1; }
      else if (b) { next = 2; }
      else
      {
        finish:
        done = 0;
      }
      break;
    case 4:
      if (c) { next = 5; }
      else { goto finish; }
      break;
    case 5:
      if (d) { next = 6; }
      else
      {
        goto finish;
      }
      break;
  }
}
'''


def test_every_goto_becomes_the_statements_of_the_label_and_the_label_goes():
    # the shared exits of a state machine in a 417-instruction input handler (with the next two families, 885 -> 20)
    (family, text), = variants(SOURCE, 'step')
    assert family == FAMILY
    assert 'goto' not in text and 'finish:' not in text
    assert text.count('done = 0;') == 3
    assert 'else { done = 0; }' in text.replace('\n', ' ').replace('  ', ' ') or 'done = 0;\n      }' in text


def test_a_goto_whose_arm_does_more_after_it_or_a_label_with_a_goto_is_left_alone():
    assert variants(SOURCE.replace('else { goto finish; }\n      break;', 'else { goto finish; }\n      extra();\n      break;'), 'step')[0][1].count('goto') == 1
    assert variants(SOURCE.replace('        done = 0;\n', '        done = 0;\n        goto finish;\n'), 'step') == []


def test_the_module_declares_itself_to_the_registry():
    assert 'goto_arm_tail_inline' in {repair.module for repair in registry.declared()}
    for repair in registry.declared():
        if repair.module == 'goto_arm_tail_inline':
            assert registry.problems(repair) == []


ARM_LEVEL = '''typedef int s32;
typedef unsigned char u8;
extern u8 gGroup;
extern s32 gKey;
void link(s32 *, u8);

void run(s32 *voice, s32 op)
{
  s32 result;
  s32 group;
  switch (op)
  {
    case 0x36:
      group = gGroup;
      block_144:
      link(voice, group);
      result = 0;
      break;

    case 0x37:
      group = voice[2] + gKey;
      if (group >= 0x100)
      {
        group = 0xFF;
      }
      group = group & 0xFF;
      goto block_144;

    case 0x38:
      result = 1;
      break;
  }
}
'''


def test_a_label_at_its_arm_level_is_copied_over_the_goto_that_ends_another_arm():
    # a sound-sequence interpreter's two group commands (KMC GCC 2.7.2): 10360 -> 9595 with the copy
    found = variants(ARM_LEVEL, 'run')
    assert len(found) == 1
    text = found[0][1]
    assert 'goto' not in text and 'block_144' not in text
    assert '''      group = group & 0xFF;
      link(voice, group);
      result = 0;
      break;

    case 0x38:''' in text
    assert text.count('link(voice, group);') == 2


EXIT_STORE = '''extern int state;
void g(void);
void run(void)
{
  int v;
  switch (state)
  {
    case 3:
      g();
      v = 4;
block_35:
      state = v;
    case 9:
    default:
      return;
    case 5:
      g();
      v = 6;
      goto block_35;
    case 7:
      v = 8;
      goto block_35;
  }
}
'''


def test_a_label_that_falls_into_an_exit_arm_is_copied_over_each_goto():
    # a state-machine dispatcher: the shared store at the first arm kept the join there (1480 -> 0)
    (family, text), = variants(EXIT_STORE, 'run')
    assert family == FAMILY
    assert 'goto' not in text and 'block_35' not in text
    assert text.count('state = v; return;') == 2
    assert 'case 9:\n    default:\n      return;' in text


def test_a_run_that_falls_into_a_working_arm_is_left_alone():
    assert variants(EXIT_STORE.replace('default:\n      return;', 'default:\n      g();\n      return;'), 'run') == []


def test_a_goto_that_does_not_end_an_arm_keeps_the_label():
    source = EXIT_STORE.replace('v = 8;\n      goto block_35;', 'v = 8;\n      goto block_35;\n      g();')
    (_, text), = variants(source, 'run')
    assert 'block_35:' in text and text.count('goto block_35;') == 1


CHAIN = '''void step(void) {
  switch (state) {
    case 4:
      if (a) {
block_86:
        output = value;
        goto block_87;
      } else if (b) {
block_87:
        state = 0;
      }
      break;
    case 3:
      if (c) { goto block_86; }
      break;
  }
}
'''


def test_a_shared_tail_whose_own_tail_is_shared_is_offered_as_one_child():
    children = [text for _, text in variants(CHAIN, 'step')]
    assert any('goto block_86' in text and 'goto block_87' not in text for text in children)
    combined = [text for text in children if 'goto block_86' not in text and 'goto block_87' not in text]
    assert combined and combined[0].count('output = value;') == 2
    assert combined[0].count('state = 0;') == 3


def test_a_break_is_not_copied_out_of_its_switch_into_a_loop():
    source = '''void step(void)
{
  do
  {
    if (c) { goto finish; }
    switch (state)
    {
      case 1:
        finish:
        done = 0;
        break;
    }
    i += 1;
  } while (i < n);
}
'''
    assert not variants(source, 'step')

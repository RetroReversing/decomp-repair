"""A 0/1 flag declared s8, a break that leaves for the return, a call arm's loop scope, the counter's step last and a
copied index in a local of its own, from a large collision sweep's last rows."""
from decomprepair import registry
from decomprepair.flag_exit_repairs import (
    ARM_SCOPE,
    BREAK_RETURN,
    INDEX_SPLIT,
    SIGNED_FLAG,
    STEP_LAST,
    variants,
)

CODE = '''typedef unsigned char u8;
typedef unsigned short u16;
typedef signed char s8;
typedef int s32;
s32 hitTest(void *);

s8 sweep(void **cell, u16 *tris, s32 n, s32 *out)
{
  u8 again;
  u8 found;
  u16 i;
  s32 temp_v1;
  s32 hit;
  void *p;
  found = 0;
  again = 1;
  p = *cell;
  do
  {
    i = 0;
    do
    {
      do { hit = hitTest(p); } while (0); if ((hit << 0x18) != 0)
      {
        out[0] += 1;
        found = 1;
      }
      temp_v1 = i; out[1] = tris[(temp_v1 * 6)] + tris[(temp_v1 * 2)] + temp_v1;
      i += 1;
      tris += 6;
      out += 3;
    }
    while (i < n);
    if (again == 0)
    {
      break;
    }
    again = 0;
    temp_v1 = n;
    if (p == 0)
    {
      break;
    }
    goto next;
    next:
    p = *((void **) p);
  }
  while (p != 0);
  return (s8) found;
}
'''


def _family(family):
    return [text for name, text in variants(CODE, 'sweep') if name == family]


def test_a_flag_only_set_to_0_or_1_is_declared_s8():
    texts = _family(SIGNED_FLAG)
    assert any('  s8 again;' in text and '  u8 found;' in text for text in texts)
    assert any('  s8 found;' in text for text in texts)


def test_a_break_before_a_goto_returns_the_closing_value():
    (text,) = _family(BREAK_RETURN)
    assert 'if (p == 0)\n    {\n      return (s8) found;\n    }\n    goto next;' in text
    assert 'if (again == 0)\n    {\n      break;' in text


def test_the_call_arm_gets_a_loop_scope():
    (text,) = _family(ARM_SCOPE)
    assert 'if ((hit << 0x18) != 0)\n      { do { ' in text
    assert 'found = 1;\n       } while (0); }' in text
    assert ARM_SCOPE not in {name for name, _ in variants(text, 'sweep')}


def test_the_counter_steps_after_the_pointer_steps():
    (text,) = _family(STEP_LAST)
    assert '      tris += 6;\n      out += 3;\n      i += 1;\n    }' in text


def test_a_reused_temporary_copied_as_an_index_gets_its_own_local():
    (text,) = _family(INDEX_SPLIT)
    assert 'temp_v1_idx = i; out[1] = tris[(temp_v1_idx * 6)] + tris[(temp_v1_idx * 2)] + temp_v1_idx;' in text
    assert '  u16 temp_v1_idx;' in text
    assert 'temp_v1 = n;' in text


def test_the_module_declares_itself():
    assert 'flag_exit_repairs' in {repair.module.rsplit('.', 1)[-1] for repair in registry.declared()}

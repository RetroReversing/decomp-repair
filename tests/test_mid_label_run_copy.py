"""A mid-block label's run, ending in a goto, copied in place of an earlier goto to it (alone and with a break
written as the closing return)."""
from decomprepair import registry
from decomprepair.mid_label_run_copy import FAMILY, variants

CODE = '''typedef unsigned char u8;
typedef signed char s8;
typedef int s32;
void push(float *);

s8 sweep(void **cell, float *out, float d, float r, s32 *kind)
{
  u8 hit;
  float s;
  void *p;
  hit = 0;
  p = *cell;
  do
  {
    if (d < r) {
      s = r - d; out[0] += s; goto tail;
    }
    if (d > r) {
      s = d - r; out[1] += s;
      tail: push(&s); if (kind != 0) { *kind = 1; } hit = 1; goto next;
    }
    next:
    if (p == 0) { break; } goto walk;
    walk:
    p = *(void **) p;
  } while (p != 0);
  return (s8) hit;
}
'''


def test_the_run_is_copied_in_place_of_the_goto():
    children = [text for family, text in variants(CODE, 'sweep') if family == FAMILY]
    copied = [t for t in children if 'out[0] += s; push(&s); if (kind != 0) { *kind = 1; } hit = 1; goto next;' in t]
    assert copied
    assert all('tail:' not in t for t in copied)


def test_the_copy_is_also_offered_with_the_break_as_the_closing_return():
    children = [text for _, text in variants(CODE, 'sweep')]
    both = [t for t in children if 'out[0] += s; push(&s);' in t and 'if (p == 0) { return (s8) hit; }' in t]
    assert both


def test_a_label_at_the_head_of_a_block_or_a_run_with_a_return_is_left_alone():
    code = CODE.replace('out[1] += s;\n      tail:', 'out[1] += s;\n      { tail:').replace('goto next;\n    }', 'goto next; }\n    }')
    assert not [t for f, t in variants(code, 'sweep') if 'out[0] += s; push' in t]
    code = CODE.replace('hit = 1; goto next;', 'return 1;')
    assert not variants(code, 'sweep')


def test_the_module_declares_itself():
    assert 'mid_label_run_copy' in {repair.module.rsplit('.', 1)[-1] for repair in registry.declared()}

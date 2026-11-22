"""A label inside the last arm of a chain, a run that every arm reaches: copied per arm, names split, steps combined.

A KMC GCC 2.7.2 state update (40 -> 0) had `if (s == 1) {..} else if (s == 2) { ..; goto L; } else { if (s == 3) {..}
else return; L: dx = a - x; dz = b - z; ... }` where arms 2 and 3 load the same four floats. Checked here on a small
function of that shape, never on game code. The family's one child has to carry every step at once: each alone leaves
the score unchanged or worse (the copy alone changed nothing the allocator sees until the names were private, the
wrappers and the union kept the arms' loads from being local, and the constant's place decided a tie)."""
import re

from decomprepair import join_tail_arm_split_repairs as repair
from decomprepair import switch_tables

CHAIN = '''void f(void *r, s32 s)
{
  union
  {
    void *pointer;
    s32 value;
  } phase;
  f32 x;
  f32 z;
  f32 u;
  f32 w;
  f32 dx;
  f32 dz;
  s32 k;
  s32 mode;
  void *q;
  if (s == 1)
  {
    dx = g_a - g_b;
    dz = g_c - g_d;
    k = 3;
  }
  else
    if (s == 2)
  {
    phase.pointer = g_rec;
    do
    {
      x = g_px;
      z = g_pz; u = *((f32 *) (((char *) phase.pointer) + 0x1A0)); w = *((f32 *) (((char *) phase.pointer) + 0x1A8)); k = *((s32 *) (((char *) phase.pointer) + 0x18C)); mode = 0;
      *((s32 *) (((char *) phase.pointer) + 0xCC)) = 0;
    }
    while (0);
    goto join;
  }
  else
  {
    mode = 0;
    if (s == 3)
    {
      do { q = g_rec; x = g_px; z = g_pz; u = *((f32 *) (((char *) q) + 0x1A0)); w = *((f32 *) (((char *) q) + 0x1A8)); k = *((s32 *) (((char *) q) + 0x18C)); *((s32 *) (((char *) q) + 0xCC)) = 0; } while (0);
    }
    else
    {
      return;
    }
    join:
    dz = w - z;
    dx = u - x;
    g_state = s + 1;
    k = k >> 12;
  }
  out:
  phase.value = use(dx, dz);
  g_out = phase.value + k + mode;
}
'''


def test_the_run_is_copied_per_arm_with_every_step_in_one_child():
    children = [text for family, text in repair.nested_run_variants(CHAIN, 'f') if family == 'goto_nested_run_copy']
    assert children
    full = children[0]
    # the copy: the goto is gone, the run is written in the arm and ends in the jump to the join the chain fell into
    assert 'goto join;' not in full or full.count('dx = u') >= 1
    assert full.count('g_state = s + 1;') == 2
    # names private to each arm
    assert re.search(r'\bx_w1\b', full) and re.search(r'\bu_w1\b', full)
    # the union split into two locals, the arms' scopes off, the constant sunk into the arm that uses it
    assert 'phase.pointer' not in full and 'phase_pointer' in full
    assert full.count('while (0)') == 0
    assert re.search(r'if \(s == 3\)\s*\{\s*mode = 0;', full)
    # the run's order swapped in some child, the original order in another
    swapped = [text for text in children if 'dx = u_w1' in text and 'dz = w_w1' in text]
    assert any(text.index('dx = u_w1') < text.index('dz = w_w1') for text in swapped)
    assert any(text.index('dz = w_w1') < text.index('dx = u_w1') for text in swapped)


def test_it_is_part_of_the_modules_variants_and_named():
    labelled = repair.variants(CHAIN, 'f')
    assert any(family == 'goto_nested_run_copy' for family, _ in labelled)
    assert 'goto_nested_run_copy' in repair.FAMILIES


def test_a_function_without_a_nested_label_gets_nothing():
    assert repair.nested_run_variants('void f(s32 a) { if (a) { g(); } }', 'f') == []


def test_a_local_union_and_case_labels_do_not_hide_the_function_from_the_outline():
    source = '''void f(s32 s)
{
  union
  {
    void *pointer;
    s32 value;
  } phase;
  switch (s)
  {
    case 1:
      do
      {
        case 2:
          g();
      }
      while (0);
      break;
    default:
      break;
  }
}
'''
    part, end, clean = repair._body(source, 'f')
    assert repair._blocks(clean, part.opening + 1, end - 1) is not None


SWITCH = '''void f(s32 s)
{
  switch (s - 2)
  {
    case 9:
      g();
      goto done;
    case 0:
    case 3:
      h();
      break;
    default:
      k();
      return;
  }
  return;
  done:
  m();
}
'''


def test_a_table_entry_the_source_has_no_case_for_gets_a_case_that_jumps_to_a_label_the_function_uses():
    # the target's entry 7 (value 7 of `s - 2`) has a destination of its own; the default is the most common one
    table = (2, [0x10, 0x30, 0x30, 0x10, 0x30, 0x30, 0x30, 0x50, 0x30, 0x20])
    children = [text for family, text in switch_tables.variants(SWITCH, 'f', [table]) if family == 'switch_gap_goto']
    assert any('case 7: goto done;' in text for text in children)
    # a value whose destination equals a present case's destination is stacked on it instead
    table = (2, [0x10, 0x30, 0x30, 0x10, 0x30, 0x10, 0x30, 0x30, 0x30, 0x20])
    children = [text for family, text in switch_tables.variants(SWITCH, 'f', [table]) if family == 'switch_gap_goto']
    assert any('case 5: case 0:' in text for text in children)


def test_no_table_or_a_complete_switch_gets_no_gap_child():
    assert switch_tables.gap_variants(SWITCH, 'f', []) == []
    full = (2, [0x10, 0x30, 0x30, 0x10, 0x30, 0x30, 0x30, 0x30, 0x30, 0x20])
    assert switch_tables.gap_variants(SWITCH, 'f', [full]) == []

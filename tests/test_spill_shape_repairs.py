from decomprepair import spill_shape_repairs as spill

NAME = 'step'

SOURCE = """\
void step(void **list, s32 mode, f32 *shift, f32 *angles, s32 mask)
{
  u8 vals[4];
  volatile u8 mirror[2];
  s32 narrow;
  u32 *cursor;
  u32 *next;
  struct
  {
    u32 pad0;
    volatile s32 mode;
    f32 * volatile angles;
    volatile u8 done;
    volatile s32 flags;
  } state;
  state.mode = mode;
  state.angles = angles;
  state.done = 0;
  narrow = *(volatile s32 *)&mask;
  if (list[0] != NULL)
  {
    cursor = list[0];
    next = cursor + 1;
    state.flags = (s8) narrow;
    do
    {
      vals[0] = next[0] * 0.015625f;
      vals[1] = next[1] * 0.015625f;
      if (state.flags)
      {
        use(state.mode, state.angles);
      }
      else
        if (mask || vals[0])
      {
        other(state.mode);
      }
      else
      {
        other(state.mode);
      }
      if (cursor[0] == 3)
      {
        state.done = 1;
      }
      next += 2;
      cursor += 2;
    }
    while (!state.done);
  }
}
"""


def one(build, source=SOURCE):
    [(family, revised)] = build(source, NAME)
    assert family in spill.FAMILIES
    return revised


def test_read_of_a_parameter_loses_its_volatile():
    revised = one(spill.volatile_read_variants)
    assert 'narrow = mask;' in revised and '(volatile s32 *)' not in revised
    assert spill.volatile_read_variants(revised, NAME) == []


def test_state_struct_becomes_plain_locals_and_parameters():
    revised = one(spill.state_unwrap_variants)
    assert 'struct' not in revised and 'volatile s32 mode' not in revised
    assert 'u8 state_done;' in revised and 's32 state_flags;' in revised
    assert revised.index('u8 state_done;') < revised.index('s32 state_flags;')
    assert 'f32 * state_angles' not in revised and 'state_mode' not in revised
    assert 'use(mode, angles);' in revised and 'state_done = 0;' in revised
    assert 'state.' not in revised and 'mode = mode' not in revised
    assert spill.state_unwrap_variants(revised, NAME) == []


def test_struct_whose_address_is_taken_stays():
    taken = SOURCE.replace('state.done = 0;', 'state.done = 0;\n  poke(&state);')
    assert spill.state_unwrap_variants(taken, NAME) == []


def prepared():
    return one(spill.state_unwrap_variants, one(spill.volatile_read_variants))


def test_copy_of_a_parameter_merges_into_its_narrow_use():
    revised = one(spill.narrow_copy_variants, prepared())
    assert 'state_flags = (s8) mask;' in revised and 'narrow' not in revised
    assert spill.narrow_copy_variants(revised, NAME) == []


def test_identical_arms_keep_one():
    revised = one(spill.arm_collapse_variants)
    assert revised.count('other(state.mode);') == 1 and 'mask || vals[0]' not in revised


def test_exit_flag_is_tested_with_a_mask():
    unwrapped = one(spill.state_unwrap_variants)
    revised = one(spill.flag_test_variants, unwrapped)
    assert 'while ((state_done & 1) == 0);' in revised
    assert spill.flag_test_variants(revised, NAME) == []
    assert spill.flag_test_variants(unwrapped.replace('state_done = 1;', 'state_done = 2;'), NAME) == []


def test_repeated_constant_is_staged_before_the_run_and_with_the_runs_swap():
    revised = spill.constant_stage_variants(one(spill.narrow_copy_variants, prepared()), NAME)
    assert len(revised) == 2
    plain, swapped = (text for _, text in revised)
    assert 'f32 repair_loop_scale;' in plain and plain.count('repair_loop_scale') == 4
    assert plain.index('repair_loop_scale = 0.015625f;') < plain.index('next = cursor + 1;')
    assert swapped.index('state_flags = (s8) mask;') < swapped.index('next = cursor + 1;')
    assert swapped.index('repair_loop_scale = 0.015625f;') < swapped.index('state_flags = (s8) mask;')
    assert spill.constant_stage_variants(plain, NAME) == []


def test_single_use_literal_is_left_alone():
    assert spill.constant_stage_variants(SOURCE.replace('next[1] * 0.015625f', 'next[1]'), NAME) == []


def test_every_family_runs_through_variants():
    names = {family for family, _ in spill.variants(SOURCE, NAME)}
    assert {'volatile_read_drop', 'volatile_state_unwrap', 'identical_arm_collapse'} <= names
    assert spill.variants('int x;', NAME) == []

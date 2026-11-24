from decomprepair import spilled_invariant_repairs as spilled

SOURCE = '''void *heap(s32);
s32 fill(s32 *, s32, s32);
void *f(s32 n, s32 flags, s32 skip)
{
  union
  {
    u8 bytes[3192];
    struct
    {
      s32 value;
    } view_sp10;
    struct
    {
      u8 pad[16];
      f32 value;
    } view_sp20;
    struct
    {
      u8 pad[20];
      f32 value;
    } view_sp24;
    struct
    {
      u8 pad[3172];
      s32 value;
    } view_spC74;
    struct
    {
      u8 pad[3180];
      s32 value;
    } view_spC7C;
  } frame;
  f32 a;
  f32 b;
  void *p;
  void *base;
  int i;
  base = heap(n);
  i = 0;
  if (n > 0)
  {
    do { do { frame.view_spC74.value = n - 1; } while (0); p = base; } while (0);
    frame.view_spC7C.value = flags & 1;
    do
    {
      b = 0.0f;
      a = 0.0f;
      fill(&frame.view_sp10.value, i, 0);
      b = frame.view_sp24.value;
      a = frame.view_sp20.value;
      if ((skip == 0) && (i == frame.view_spC74.value))
      {
        a = 1.0f;
      }
      if (flags & 2)
      {
        b = a;
      }
      if (frame.view_spC7C.value)
      {
        a = b;
      }
      i += 1;
      *((f32 *) (((char *) p) + 0xC)) = a; p = p + 4;
    }
    while (n > i);
  }
  return base;
}
'''


def families(out):
    return {family: text for family, text in out}


def test_a_scalar_view_past_every_address_taken_one_becomes_a_local_and_the_union_shrinks():
    text = spilled.spilled_view_local(SOURCE, 'f')
    assert 'u8 bytes[3168];' in text
    assert 'view_spC74' not in text and 'view_spC7C' not in text
    assert 'spill_C74 = n - 1;' in text and 'spill_C74;' in text.split('} frame;')[1]
    assert 'do { do {' not in text  # the weight-raising wrapper around the hoisted expression is gone
    assert 'view_sp24' in text  # the members whose address or offset the calls use stay


def test_nothing_is_proposed_without_a_frame_union():
    assert spilled.spilled_view_local('void f(void)\n{\n  int a;\n  a = 1;\n}\n', 'f') is None


def test_a_zero_local_is_declared_after_the_others_and_replaces_the_literal():
    text = spilled.late_constant_local(SOURCE, 'f')[0]
    declared = text.split('} frame;')[1]
    assert declared.index('int i;') < declared.index('int late_zero;')
    assert 'late_zero = 0;\n  if (n > late_zero)' in text


def test_a_walked_pointer_store_becomes_an_indexed_store_after_the_counter_moves():
    text = spilled.walk_index_form(SOURCE, 'f')[0]
    assert '((f32 *) base)[i + 3] = a; i += 1;' in text
    assert 'void *p;' not in text and 'p = base;' not in text and 'p = p + 4' not in text


def test_an_and_condition_becomes_two_nested_ifs():
    text = spilled.nested_and_if(SOURCE, 'f')[0]
    assert 'if (skip == 0)' in text and 'if (i == frame.view_spC74.value)' in text and '&&' not in text


def test_loads_from_the_union_follow_the_members_offsets():
    text = spilled.address_load_order(SOURCE, 'f')[0]
    assert text.index('a = frame.view_sp20.value;') < text.index('b = frame.view_sp24.value;')


def test_mask_tests_run_in_ascending_mask_order_with_a_spilled_local_counting_as_its_mask():
    local = spilled.spilled_view_local(SOURCE, 'f')
    text = spilled.mask_test_order(local, 'f')[0]
    assert text.index('if (spill_C7C)') < text.index('if (flags & 2)')


def test_the_combined_child_applies_them_all_and_variants_names_every_family():
    out = families(spilled.variants(SOURCE, 'f'))
    # a mask test needs the spilled local first; that source has no two-mask tests
    assert set(out) == set(spilled.FAMILIES) - {spilled.MASKS, spilled.NEST_MASKS}
    whole = out[spilled.COMBINED]
    assert 'late_zero' in whole and '((f32 *) base)[i + 3]' in whole and 'spill_C74' in whole and '&&' not in whole
    assert whole.index('if (spill_C7C)') < whole.index('if (flags & 2)')


MASKS = """void g(int);
void f(int *p, int n, int m)
{
  int a;
  int b;
  if ((n > 0) && (m > 0)) { g(1); }
  if ((n > 1) && (m > 1)) { g(2); }
  if ((n > 2) && (m > 2)) { g(3); }
  if ((n > 3) && (m > 3)) { g(4); }
  if ((n > 4) && (m > 4)) { g(5); }
  a = p[0] >> 23;
  if ((!(a & 0x80)) && (!(a & 0x20)))
  {
    g(a);
  }
  b = p[1] >> 23;
  if ((!(b & 0x80)) && (!(b & 0x20)))
  {
    g(b);
  }
}
"""


def test_two_mask_tests_past_the_first_four_ifs_are_offered_and_nested_together():
    children = spilled.variants(MASKS, 'f')
    every = dict(children)[spilled.NEST_MASKS]
    assert 'if (!(a & 0x80))' in every and 'if (!(a & 0x20))' in every
    assert 'if (!(b & 0x80))' in every and 'if (!(b & 0x20))' in every
    singles = [text for family, text in children if family == spilled.NEST]
    assert any('if (!(a & 0x80))' in t and '(!(b & 0x80)) &&' in t for t in singles)
    assert any('if (!(b & 0x80))' in t and '(!(a & 0x80)) &&' in t for t in singles)

from decomprepair.join_clamp_sum_repairs import FAMILY_CLAMP, FAMILY_COPY, FAMILY_SUM, variants

CLAMP = """
s32 f(void *state) {
  u8 temp_v1;
  u8 var_s1_2;
  temp_v1 = *((u8 *) (((char *) state) + 0x30));
  if ((temp_v1 + 1) < (0xFFU + 1))
  {
    var_s1_2 = temp_v1;
  }
  else
  {
    var_s1_2 = 0xFF;
  }
  return var_s1_2;
}
"""


def test_a_byte_plus_one_clamp_compares_the_byte_itself():
    [(family, revised)] = [item for item in variants(CLAMP, 'f') if item[0] == FAMILY_CLAMP]
    assert family == FAMILY_CLAMP
    assert 'if (temp_v1 < 0xFFU)' in revised and '+ 1)' not in revised


def test_the_clamp_needs_a_narrow_unsigned_local_and_a_limit_that_fits():
    assert not [i for i in variants(CLAMP.replace('u8 temp_v1;', 's32 temp_v1;'), 'f') if i[0] == FAMILY_CLAMP]
    assert not [i for i in variants(CLAMP.replace('0xFFU + 1', '0x100U + 1'), 'f') if i[0] == FAMILY_CLAMP]


COPY = """
void g(void *arg0, void *entry)
{
  void *temp_a0;
  void *temp_v1_2;
  f32 temp_fv1;
  s32 var_v1;
  temp_v1_2 = *((void **) (((char *) entry) + 8));
  if (temp_v1_2 != NULL)
  {
    temp_fv1 = *((f32 *) (((char *) arg0) + 0xC));
    if (!(temp_fv1 >= 2147483648.0f))
    {
      var_v1 = (s32) temp_fv1;
    }
    else
    {
      var_v1 = ((s32) (temp_fv1 - 2147483648.0f)) | 0x80000000;
    }
    *((u8 *) (((char *) temp_v1_2) + 0x29)) = var_v1;
    temp_a0 = *((void **) (((char *) entry) + 8));
    *((u8 *) (((char *) temp_a0) + 0x29)) = 0;
  }
}
"""


def test_a_pointer_copy_is_made_before_the_diamond_and_read_after_it():
    [(family, revised)] = [item for item in variants(COPY, 'g') if item[0] == FAMILY_COPY]
    assert family == FAMILY_COPY
    assert revised.index('temp_a0 = temp_v1_2;') < revised.index('temp_fv1 = ')
    assert '*((u8 *) (((char *) temp_a0) + 0x29)) = var_v1;' in revised


def test_the_copy_needs_a_join_and_a_pointer_the_function_sets_elsewhere():
    # No `if` inside the guard: no join between the check and the store.
    start = COPY.index('    if (!(temp_fv1')
    end = COPY.index('    *((u8 *) (((char *) temp_v1_2)')
    flat = COPY[:start] + '    var_v1 = (s32) temp_fv1;\n' + COPY[end:]
    assert not [i for i in variants(flat, 'g') if i[0] == FAMILY_COPY]
    never = COPY.replace('    temp_a0 = *((void **) (((char *) entry) + 8));\n', '')
    assert not [i for i in variants(never, 'g') if i[0] == FAMILY_COPY]
    # A copy variable already used between the check and the store is not touched.
    busy = COPY.replace('var_v1 = (s32) temp_fv1;', 'temp_a0 = NULL;')
    assert not [i for i in variants(busy, 'g') if i[0] == FAMILY_COPY]


SUM = """
void h(void *dst, void *src, s32 var_v1)
{
  *((s16 *) (((char *) dst) + 0x22)) = (s16) (var_v1 + (*((u16 *) (((char *) src) + 0x1A))));
}
"""


def test_a_narrowed_sum_is_made_full_width_in_a_local_first():
    [(family, revised)] = [item for item in variants(SUM, 'h') if item[0] == FAMILY_SUM]
    assert family == FAMILY_SUM
    assert 's32 wide_sum;' in revised
    assert 'wide_sum = var_v1 + (*((u16 *) (((char *) src) + 0x1A)));' in revised
    assert '*((s16 *) (((char *) dst) + 0x22)) = (s16) wide_sum;' in revised


def test_a_sum_with_a_call_or_a_third_term_is_left_alone():
    assert not [i for i in variants(SUM.replace('var_v1 +', 'get(var_v1) +'), 'h') if i[0] == FAMILY_SUM]
    assert not [i for i in variants(SUM.replace('var_v1 +', 'var_v1 + 1 +'), 'h') if i[0] == FAMILY_SUM]

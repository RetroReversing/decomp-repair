from decomprepair.phase_donor_repairs import ADDRESS, FAMILY, PRODUCT, SCALAR, variants

# Two halves that each clamp a scaled difference and add it to a halfword of a record (the shape of a 181-instruction
# N64 function, written small): the second half's clamp variable is a union member a phase repair added, its record
# pointer is a pointer local of its own and its product has no variable at all.
SOURCE = '''void f(void *arg0, s32 arg2, s32 arg3, s32 limit)
{
  s32 var_a0;
  s32 var_v1;
  s32 var_a1;
  register union
  {
    void *pointer;
    s32 value;
  } phase;
  register void *second;
  void *base;
  phase.pointer = *((void **) (((char *) arg0) + 0x68));
  base = (void *) (0x14 + ((s32) phase.pointer));
  var_v1 = arg2 * 2;
  var_v1 = var_v1 + ((s32) base);
  var_a0 = (limit - *((s16 *) (((char *) var_v1) + 0x94))) * arg3;
  var_a0 >>= 7;
  if (var_a0 < (-0x40))
  {
    var_a0 = -0x40;
  }
  *((s16 *) (((char *) var_v1) + 0x94)) += var_a0;
  var_a1 = limit - *((s16 *) (((char *) base) + 0x98));
  phase.value = ((s32) (var_a1 * arg3)) >> 7;
  if (phase.value < (-0x40))
  {
    phase.value = -0x40;
  }
  second = (void *) ((arg2 * 2) + base);
  *((s16 *) (((char *) second) + 0x98)) += phase.value;
}
'''


def texts(source=SOURCE):
    return dict((family, text) for family, text in variants(source, 'f'))


def test_the_whole_combination_comes_first_as_one_child():
    first_family, first = variants(SOURCE, 'f')[0]
    assert first_family == FAMILY
    # the union member became a plain local, the product runs through the first clamp's dead variable, and the
    # second record pointer is the first one's variable
    assert 'phase_value' in first and 'phase.value' not in first
    assert 'var_a0 = var_a1 * arg3; phase_value = var_a0 >> 7;' in first
    assert 'var_v1 = (s32) ((arg2 * 2) + base);' in first
    assert 'second' not in first
    assert '((char *) ((void *) var_v1)) + 0x98' in first


def test_each_step_is_offered_alone_too():
    families = {family for family, _ in variants(SOURCE, 'f')}
    assert families == {FAMILY, SCALAR, ADDRESS, PRODUCT}
    alone = [text for family, text in variants(SOURCE, 'f') if family == PRODUCT]
    assert alone and 'var_a0 = var_a1 * arg3; phase.value = var_a0 >> 7;' in alone[0]


def test_a_donor_still_read_afterwards_is_not_reused():
    later = SOURCE.replace('*((s16 *) (((char *) second) + 0x98)) += phase.value;',
                           '*((s16 *) (((char *) second) + 0x98)) += phase.value + var_a0;')
    assert not [t for f, t in variants(later, 'f') if 'var_a0 = var_a1 * arg3' in t]


def test_a_function_with_a_loop_is_left_alone_for_the_donor_steps():
    looped = SOURCE.replace('  var_a1 = limit', '  while (arg2) { arg2 -= 1; }\n  var_a1 = limit')
    assert {family for family, _ in variants(looped, 'f')} <= {SCALAR}


def test_a_product_without_a_dead_donor_is_not_rewritten():
    single = '''void f(s32 a, s32 b)
{
  s32 v;
  v = ((s32) (a * b)) >> 7;
  use(v);
}
'''
    assert variants(single, 'f') == []


def test_nothing_changes_the_original_semantics_of_the_untouched_text():
    for _, text in variants(SOURCE, 'f'):
        assert text.count('{') == text.count('}')
        assert 'phase.pointer = ' in text

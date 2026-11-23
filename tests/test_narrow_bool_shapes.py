from decomprepair.narrow_bool_shapes import FAMILIES, REPAIR, variants

SOURCE = """typedef unsigned short u16;
typedef signed int s32;
typedef struct { signed char idx; unsigned char flags; } Slot;
inline static Slot *slot_at(u16 arg0, int arg1, unsigned int arg2)
{
  return (Slot *) ((arg0 * arg1) + arg2);
}

void run(Slot *base, s32 mask, s32 bonus)
{
  s32 i = 0;
  s32 t2;
  s32 t3;
  Slot *e;
  do {
    e = slot_at((u16) i, sizeof(*base), (unsigned int) base);
    t2 = (mask & e->flags) != 0;
    t2 = t2 == 0;
    t3 = bonus == 0;
    if (((u16) t3) & t2) {
      continue;
    }
    i++;
  } while (base[i].idx != -1);
}
"""


def _all(family, source=SOURCE):
    return [text for name, text in variants(source, 'run') if name == family]


def test_the_helper_call_is_expanded_with_its_halfword_parameter_kept_as_a_local():
    text = _all('narrow_param_unwrap')[0]
    assert 'u16 slot_at_arg0;' in text
    assert 'slot_at_arg0 = (u16) i;' in text
    assert 'e = (Slot *) ((slot_at_arg0 * sizeof(*base)) + ((unsigned int) base));' in text
    assert 'e = slot_at(' not in text


def test_a_helper_without_a_narrow_parameter_is_left_alone():
    source = SOURCE.replace('inline static Slot *slot_at(u16 arg0,', 'inline static Slot *slot_at(int arg0,')
    assert _all('narrow_param_unwrap', source) == []


def test_two_single_use_comparison_temps_become_one_expression_in_both_orders():
    texts = _all('bool_pair_inline')
    assert any('if ((t2 == 0) & (bonus == 0))' in text for text in texts)
    assert any('if ((bonus == 0) & (t2 == 0))' in text for text in texts)
    assert all('t3 = bonus == 0;' not in text for text in texts)


def test_a_temp_read_after_the_test_keeps_the_statements():
    source = SOURCE.replace('    i++;', '    i += t3;')
    assert _all('bool_pair_inline', source) == []


def test_a_call_in_a_comparison_is_not_moved_into_the_test():
    source = SOURCE.replace('t3 = bonus == 0;', 't3 = check(bonus) == 0;')
    assert _all('bool_pair_inline', source) == []


def test_both_edits_are_offered_as_one_child():
    both = _all('narrow_bool_shapes')[0]
    assert 'slot_at_arg0 = (u16) i;' in both and 'if ((t2 == 0) & (bonus == 0))' in both


def test_the_module_declares_itself():
    assert REPAIR['families'] == FAMILIES and REPAIR['variants'] is variants

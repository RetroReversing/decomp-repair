from decomprepair.element_update_repairs import FAMILIES, variants

SOURCE = """static inline u8 column_of(void *rec)
{
  return ((Field_u8 *) (((char *) rec) + 0x34))->v;
}

void bump(void *rec, s32 cond)
{
  s32 *slot;
  rec_store(rec);
  if (cond != 0) {
    slot = &table[((Field_u8 *) (((char *) rec) + 0x33))->v][column_of(rec)];
    *slot += 1;
  }
  rec_out(rec, table[((Field_u8 *) (((char *) rec) + 0x33))->v][column_of(rec)]);
}
"""


def _by_family(source=SOURCE):
    return {family: text for family, text in variants(source, 'bump')}


def test_the_address_local_becomes_an_in_place_update():
    text = _by_family()['element_pointer_compound']
    assert 'table[((Field_u8 *) (((char *) rec) + 0x33))->v][column_of(rec)] += 1;' in text
    assert 'slot = &' not in text and 'column_of(rec)]' in text


def test_the_one_line_helper_is_expanded_at_each_call():
    text = _by_family()['index_helper_unwrap']
    assert 'column_of(rec)' not in text.split('void bump')[1]
    assert text.count('((Field_u8 *) (((char *) rec) + 0x34))->v') == 3  # the helper's own body and two calls
    assert 'slot = &' in text


def test_the_pair_is_offered_as_one_child():
    both = _by_family()['element_update_shape']
    assert 'slot = &' not in both and 'column_of(rec)' not in both.split('void bump')[1]
    assert '+= 1;' in both


def test_a_pointer_used_elsewhere_or_a_call_in_the_address_is_left_alone():
    elsewhere = SOURCE.replace('rec_store(rec);', 'rec_store(slot);')
    assert 'element_pointer_compound' not in _by_family(elsewhere)
    called = SOURCE.replace('slot = &table[', 'slot = &pick(rec)[')
    assert 'element_pointer_compound' not in _by_family(called)


def test_nothing_without_the_shapes_or_with_asm():
    assert not variants('void f(void) { g(); }\n', 'f')
    assert not variants(SOURCE.replace('rec_store(rec);', 'asm("nop");'), 'bump')
    assert set(FAMILIES) == {'element_pointer_compound', 'index_helper_unwrap', 'element_update_shape'}


def test_inline_static_order_is_read_too():
    reordered = SOURCE.replace('static inline u8', 'inline static u8')
    assert 'element_update_shape' in _by_family(reordered)

from decomprepair.phase_storage_split_repairs import COMBINED, FAMILY, variants

SOURCE = """void f(s32 *arg0, u8 flag)
{
  s32 x;
  union
  {
    s32 *pointer;
    s32 value;
  } store;
  store.pointer = arg0;
  if (store.pointer == NULL)
  {
    store.pointer = table;
  }
  fill(store.pointer);
  store.value = 0xA0;
  x = 0;
  if (((s8) flag) == 0)
  {
    x = 1;
  }
  if (((s8) flag) != 0)
  {
    x = 2;
  }
  use2(x, store.value);
}
"""


def _by_family(source=SOURCE):
    return {family: text for family, text in variants(source, 'f')}


def test_a_local_union_becomes_one_local_per_member():
    text = _by_family()[FAMILY]
    assert 'union' not in text
    assert 's32 * store_pointer;' in text or 's32 *store_pointer;' in text
    assert 's32 store_value;' in text
    assert 'store.' not in text and 'store_pointer = arg0;' in text and 'use2(x, store_value);' in text


def test_the_pair_with_the_shared_narrow_test_is_offered_as_one_child():
    text = _by_family()[COMBINED]
    assert 'store.' not in text and text.count('(s8)') == 1


def test_a_union_used_whole_or_a_function_without_one_is_left_alone():
    assert not variants(SOURCE.replace('fill(store.pointer);', 'fill(&store);'), 'f')
    assert not variants(SOURCE.replace('fill(store.pointer);', 'copy(store);'), 'f')
    assert not variants('void f(void) { g(); }\n', 'f')


def test_a_union_with_a_brace_initializer_gives_its_first_member_the_value():
    source = SOURCE.replace('  } store;\n  store.pointer = arg0;', '  } store = {&table[1]};\n  store.pointer = arg0;')
    text = _by_family(source)[FAMILY]
    assert 'union' not in text and 'store.' not in text
    assert 's32 *store_pointer = &table[1];' in text or 's32 * store_pointer = &table[1];' in text
    assert 's32 store_value;' in text

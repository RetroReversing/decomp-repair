"""union_pointer_reuse: a union's late pointer phase written as the earlier pointer local (an N64 sound setup routine,
SN GCC -O2: the union split alone tied at 120, the pair scored 60). The source below is made up."""
from decomprepair import registry
from decomprepair import union_pointer_reuse as reuse

SOURCE = """void *get(void);
void g(s32 n)
{
  void *slot;
  union
  {
    void *pointer;
    s32 value;
  } store;
  store.value = 0;
  do {
    slot = get();
    if (slot != NULL)
    {
      fill(slot);
    }
    store.value += 1;
  } while (store.value < n);
  store.pointer = get();
  if (store.pointer != NULL)
  {
    fill(store.pointer);
  }
}
"""


def test_the_late_pointer_phase_is_written_into_the_earlier_pointer():
    texts = [text for family, text in reuse.variants(SOURCE, 'g') if family == 'union_pointer_reuse']
    assert any('union' not in text and 'store_pointer' not in text and text.count('slot = get();') == 2
               and 'fill(slot);' in text and 'store_value += 1;' in text for text in texts)


def test_a_union_pointer_alive_with_the_other_pointer_stays_apart():
    overlapping = SOURCE.replace('    fill(store.pointer);\n', '    fill(store.pointer);\n    fill(slot);\n')
    overlapping = overlapping.replace('  store.pointer = get();', '  slot = get();\n  store.pointer = get();')
    assert not reuse.variants(overlapping, 'g')


def test_without_a_union_there_is_nothing_to_do():
    assert not reuse.variants('void g(void)\n{\n  void *p;\n  p = 0;\n  fill(p);\n}\n', 'g')


def test_it_is_declared_in_the_registry():
    assert 'union_pointer_reuse' in {r.module.rsplit('.', 1)[-1] for r in registry.declared()}

"""A guarded `do { } while` over a counter, written as the `for` loop (and the whole chain from volatile cursors)."""
from decomprepair import registry
from decomprepair.guarded_counter_for_loop import FAMILY, STEPPED, variants

HELPER = '''inline static s32 count_of(void *arg0)
{
  return (s32) (*((u16 *) (((u8 *) arg0) + 0x40)));
}
'''
SOURCE = HELPER + '''
s32 walk(void *rec, s32 *out)
{
  s32 i;
  void *m;
  s32 r;
  m = *((void **) rec); i = 0;
  r = 0;
  if (count_of(m) > 0)
  {
    do
    {
      r += g(i, out);
      i += 1;
    }
    while (i < ((s32) (*((u16 *) (((u8 *) m) + 0x40)))));
  }
  return r;
}
'''
CURSORS = HELPER + '''
void trace(void *arg0, u8 *table, s32 *out)
{
  s32 i;
  volatile s32 off3;
  volatile s32 off6;
  volatile s64 pad[2];
  void *m;
  m = *((void **) arg0); i = 0;
  if (count_of(m) > 0)
  {
    off3 = 0; off6 = 0;
    do
    {
      if (*(u8 *) ((u8 *) m + 0x48) & 4)
      {
        if (D_80100000)
        {
          out[0] = *(s32 *) (table + off6);
        }
        else
        {
          out[0] = *(s32 *) (table + off6);
        }
      }
      else
      {
        out[1] = *(s32 *) (table + off3);
      }
      if (*(s32 *) ((u8 *) arg0 + 0x4C))
      {
        off3 += 3;
        i += 1;
        off6 += 6;
      }
      else
      {
        off3 += 3;
        i += 1;
        off6 += 6;
      }
    }
    while (i < ((s32) (*((u16 *) (((u8 *) m) + 0x40)))));
  }
}
'''


def test_the_guard_through_the_helper_and_the_do_loop_become_one_for_loop():
    # a 529-instruction N64 function: the guard's call through an identity helper was one reference less than the plain
    # bound, and the loop's copied test left no pseudo for the frame's spill area (1486 -> 500 after the cursors)
    (family, text), = variants(SOURCE, 'walk', only=FAMILY)
    assert family == FAMILY
    assert 'for (i = 0; i < ((s32) (*((u16 *) (((u8 *) m) + 0x40)))); i++)' in text
    assert 'i += 1;' not in text and 'do' not in text.replace('inline static', '')
    assert text.count('i = 0;') == 1 and 'm = *((void **) rec);' in text
    assert 'r += g(i, out);' in text


def test_the_same_guard_without_a_helper_is_the_bound_itself():
    bare = SOURCE.replace('count_of(m) > 0', '((s32) (*((u16 *) (((u8 *) m) + 0x40)))) > 0')
    assert len(variants(bare, 'walk', only=FAMILY)) == 1


def test_a_guard_that_is_not_the_loop_s_bound_or_a_counter_that_escapes_is_left_alone():
    assert variants(SOURCE.replace('count_of(m) > 0', 'count_of(m) > 1'), 'walk', only=FAMILY) == []
    assert variants(SOURCE.replace('count_of(m) > 0', 'count_of(rec) > 0'), 'walk', only=FAMILY) == []
    assert variants(SOURCE.replace('r += g(i, out);', 'if (r) continue; r += g(i, out);'), 'walk', only=FAMILY) == []
    assert variants(SOURCE.replace('r += g(i, out);', 'i = 2; r += g(i, out);'), 'walk', only=FAMILY) == []
    assert variants(SOURCE.replace('  r = 0;\n', '  r = i;\n'), 'walk', only=FAMILY) == []
    assert variants(SOURCE.replace('m = *((void **) rec); i = 0;', 'm = *((void **) rec); i = 1;'), 'walk', only=FAMILY) == []


def test_volatile_cursors_the_identical_arms_and_the_loop_come_as_one_child():
    # 922 -> 1263 (cursors) -> 1486 (identical arms) -> 500 (the `for`): a greedy chain stops at the first
    children = variants(CURSORS, 'trace')
    chain = [text for family, text in children if family == STEPPED]
    assert chain
    text = chain[0]
    assert 'volatile' not in text and 'pad' not in text and 'off3' not in text and 'off6' not in text
    assert 'for (i = 0; i < ((s32) (*((u16 *) (((u8 *) m) + 0x40)))); i++)' in text
    assert 'table + (i * 6)' in text and 'table + (i * 3)' in text and 'D_80100000' not in text
    assert text.count('0x4C') == 0


def test_the_module_declares_itself_to_the_registry():
    modules = {repair.module for repair in registry.declared()}
    assert 'guarded_counter_for_loop' in modules
    for repair in registry.declared():
        if repair.module == 'guarded_counter_for_loop':
            assert registry.problems(repair) == []

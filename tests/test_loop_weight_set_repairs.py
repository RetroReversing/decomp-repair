"""Every start and step of the second loop's locals wrapped at once (KMC GCC 2.7.2 priorities, a hypothesis)."""
from decomprepair import loop_weight_set_repairs as r

SOURCE = '''void init_tables(void *arg0)
{
  union
  {
    u8 *pointer;
    s32 value;
  } phase;
  s32 first_offset;
  u32 counter;
  u32 arg;
  void *record;
  void *cursor;
  void *walker;
  counter = 0;
  record = *((void **) (((char *) arg0) + 0x6C));
  phase.pointer = &flag;
  first_offset = 0;
  walker = record;
  first_loop:
  {
    if ((*phase.pointer) != 0)
    {
      *((u16 *) (((char *) walker) + 0x1BC)) = *((u16 *) (((u8 *) table_a) + first_offset));
    }
    walker += 2;
    do
    {
      counter += 1;
    }
    while (0);
    first_offset += 4;
  }
  if (counter < 0x20U)
  {
    goto first_loop;
  }
  counter = 0;
  phase.value = 0;
  first_offset = 0;
  cursor = record;
  second_loop:
  {
    *((u8 *) (((char *) cursor) + 0x1FC)) = (u8) table_b[phase.value];
    phase.value += 0xE8;
    first_offset += 8;
    cursor += 8;
    arg = counter;
    counter += 1;
    call(arg);
  }
  if (counter < 0x3BU)
  {
    goto second_loop;
  }
}
'''


def texts(source=SOURCE):
    return [text for family, text in r.variants(source, 'init_tables') if family == r.FAMILY]


def test_the_second_loop_is_wrapped_with_the_induction_pointer_three_deep():
    wanted = ('do { do { do { cursor += 8; } while (0); } while (0); } while (0);',
              'do { phase_value += 0xE8; } while (0);',
              'do { arg = counter; counter += 1; } while (0);',
              'do { first_offset_b1 += 8; } while (0);')
    hits = [text for text in texts() if all(piece in text for piece in wanted)]
    assert hits
    # the first loop's own offset and pointer keep their weights; its counter's step is the shared one
    assert any('do { walker += 2; } while (0);' not in text and 'do { first_offset += 4; } while (0);' not in text
               and '/*__repair_loop_weight*/do { counter += 1; } while (0);' in text for text in hits)


def test_the_union_and_the_reused_offset_are_split_in_the_same_child():
    text = next(text for text in texts() if 'phase_value' in text)
    assert 'union' not in text and 'first_offset_b1' in text


def test_a_marked_source_is_refused():
    marked = texts()[0]
    assert r.variants(marked, 'init_tables') == []


def test_a_volatile_or_a_single_local_is_refused():
    assert r.variants(SOURCE.replace('u32 arg;', 'volatile u32 arg;'), 'init_tables') == []
    one = 'void f(void)\n{\n  u32 i;\n  i = 0;\n  i += 1;\n}\n'
    assert r.variants(one, 'f') == []

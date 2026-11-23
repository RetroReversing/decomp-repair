"""A byte global read into a word local early, for the guard and the call it passes to.

Synthetic shape of the tail of a mixing function (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`). The exact-judge replay
is in decompdecomp's tests (it needs the compiler): 220 -> 100 with the read after the cursor flip, 1680 -> 1560 on the
saved best."""
from decomprepair import early_global_byte_copy as m
from decomprepair import registry

SOURCE = '''typedef unsigned char u8;
typedef int s32;
extern u8 g_cursor;
extern u8 g_pending;
extern s32 g_table;
extern s32 g_out;
void flip(void)
{
  s32 next;
  s32 *slot;
  settle();
  next = g_cursor ^ 1;
  slot = &g_table;
  g_out = next;
  if (g_pending != 0)
  {
    notify(slot, g_pending);
    g_pending = 0;
  }
}
'''


def texts(source=SOURCE):
    found = m.variants(source, 'flip')
    assert all(family == m.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_read_goes_after_an_earlier_statement_and_feeds_the_guard_and_the_call():
    found = texts()
    after_next = next(t for t in found if '  next = g_cursor ^ 1;\n  __repair_early_0 = g_pending;\n' in t)
    assert 'u32 __repair_early_0;' in after_next
    assert 'if (__repair_early_0 != 0)' in after_next
    assert 'notify(slot, __repair_early_0);' in after_next
    assert 'g_pending = 0;' in after_next  # the write keeps the global


def test_a_call_between_the_read_and_the_guard_is_not_crossed():
    called = SOURCE.replace('  slot = &g_table;', '  settle();\n  slot = &g_table;')
    found = texts(called)
    assert found
    for text in found:
        assert text.index('__repair_early_0 = g_pending;') > text.index('settle();', text.index('next = g_cursor'))


def test_a_global_that_the_guard_region_writes_is_not_read_early():
    written = SOURCE.replace('  g_out = next;', '  g_pending = 3;')
    found = texts(written)
    assert found
    assert all(t.index('__repair_early_0 = g_pending;') > t.index('g_pending = 3;') for t in found)


def test_a_read_inside_a_conditional_block_is_never_chosen():
    inside = SOURCE.replace('  next = g_cursor ^ 1;', '  if (next)\n  {\n    next = g_cursor ^ 1;\n  }')
    assert all('    next = g_cursor ^ 1;\n    __repair_early' not in t for t in texts(inside))


def test_it_declares_itself_to_the_registry():
    assert any(r.module == 'early_global_byte_copy' for r in registry.declared())

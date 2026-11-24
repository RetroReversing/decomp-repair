"""A loop bound copied out of a global read from the global, the loop's byte-offset stores as members."""
from decomprepair.loop_global_bound_member_store import FAMILY, variants

# A sound-sequence interpreter's voice scan (KMC GCC 2.7.2, N64).
SCAN = '''void f(u32 key)
{
  long i;
  s32 off;
  s32 h;
  {
    u32 count = gCount;
    for (i = 0; i < count; i++)
    {
      off = i * 0x1A0;
      h = *((s32 *) (((char *) (&gHandles)) + off));
      if (h == (key | i))
      {
        *((s32 *) (((char *) (&gFlags)) + off)) |= 8;
      }
    }
  }
  i = 0;
}
'''


def _children(text):
    return [src for fam, src in variants(text, 'f') if fam == FAMILY]


def test_the_bound_reads_the_global_and_the_store_is_a_member():
    want = ('typedef struct { s32 w; } RepairWordS32;\n' + SCAN.replace('    u32 count = gCount;\n', '')
            .replace('i < count', 'i < gCount').replace('  {\n    for', '  {\n    u32 i;\n    for', 1)
            .replace('*((s32 *) (((char *) (&gFlags)) + off)) |= 8;', '((RepairWordS32 *) (((char *) (&gFlags)) + off))->w |= 8;'))
    assert _children(SCAN) == [want]


def test_a_counter_read_after_the_loop_keeps_its_own_declaration_and_the_loop_is_left_alone():
    assert _children(SCAN.replace('  i = 0;\n', '  use(i);\n')) == []


def test_a_loop_without_a_byte_offset_store_is_left_alone():
    assert _children(SCAN.replace('*((s32 *) (((char *) (&gFlags)) + off)) |= 8;', 'mark(h);')) == []


def test_a_bound_read_elsewhere_is_left_alone():
    assert _children(SCAN.replace('  i = 0;\n', '  i = 0;\n  use(count);\n').replace('  {\n    u32 count', '  {\n    u32 count', 1)) == []

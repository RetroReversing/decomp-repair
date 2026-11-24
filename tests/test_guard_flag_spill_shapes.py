"""Guards, spill slots and float temporaries of a large collision sweep."""
import re

from decomprepair import registry
from decomprepair.guard_flag_spill_shapes import COUNTER, FLAG_SHARE, FLOAT_MERGE, READ_FIRST, variants

CODE = '''typedef unsigned char u8;
typedef unsigned short u16;
typedef int s32;
typedef unsigned int u32;
typedef float f32;
typedef struct { f32 v[3]; } V3;
typedef struct { u8 v; } Field_u8;
s32 hit(void *, s32);

s32 sweep(void *a, void *b, f32 *p, f32 r, s32 n)
{
  s32 i;
  s32 j;
  u32 flag;
  f32 y;
  f32 lo[3];
  f32 hi[3];
  f32 temp_fa0;
  f32 temp_fa0_3;
  f32 d;
  f32 x0;
  f32 x1;
  flag = ((Field_u8 *) (((char *) a) + 0x48))->v & 4;
  if (flag != 0)
  {
    if (flag < n)
    {
      i = 0;
      do { hit(a, i); i++; } while (i < n);
    }
  }
  *((V3 *) hi) = *((V3 *) p);
  *((V3 *) lo) = *((V3 *) hi);
  y = p[1];
  if ((((Field_u8 *) (((char *) b) + 0x48))->v & 4) != 0)
  {
    hit(b, 0);
  }
  { j = 0; }
  if ((((Field_u8 *) (((char *) b) + 0x48))->v & 4) < n)
  {
    do { hit(b, j); j++; } while (j < n);
  }
  temp_fa0 = r - y;
  x0 = temp_fa0 * lo[0];
  temp_fa0_3 = r - lo[1];
  x1 = temp_fa0_3 * hi[0];
  d = r - d;
  x0 = d * hi[1];
  x1 = d * hi[2];
  return (s32) (x0 + x1 + y);
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def by_family(family):
    return [child for name, child in variants(CODE, 'sweep') if name == family]


def test_the_read_moves_above_the_copies():
    (child,) = by_family(READ_FIRST)
    assert 'y = p[1]; *((V3 *) hi) = *((V3 *) p);' in squash(child)


def test_the_later_tests_go_through_the_flag_local_and_the_counters_become_u16():
    alone, with_counters = by_family(FLAG_SHARE)
    text = squash(alone)
    assert 'flag = ((Field_u8 *) (((char *) b) + 0x48))->v & 4; if (flag != 0)' in text
    assert 'if (flag < n) { do { hit(b, j)' in text
    both = squash(with_counters)
    assert 'u16 i;' in both and 'u16 j;' in both
    assert 'i = 0; if (flag < n) {' in both


def test_a_counter_zeroed_in_its_guard_moves_above_it_as_u16():
    (child,) = by_family(COUNTER)
    text = squash(child)
    assert 'u16 i;' in text and 'i = 0; if (flag < n) { do' in text


def test_the_push_out_temporaries_become_one_float():
    merged, rewritten = by_family(FLOAT_MERGE)
    assert 'temp_fa0_3' not in merged
    text = squash(rewritten)
    assert 'temp_fa0 = r - d; x0 = temp_fa0 * hi[1]; x1 = temp_fa0 * hi[2];' in text


def test_the_module_declares_itself():
    assert 'guard_flag_spill_shapes' in {repair.module.rsplit('.', 1)[-1] for repair in registry.declared()}

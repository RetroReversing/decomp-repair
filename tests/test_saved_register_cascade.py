"""Five allocation shapes of a large collision sweep, one by one and the measured three together."""
import re

from decomprepair import registry
from decomprepair.saved_register_cascade import (
    BIV_ARM,
    CALL_SCOPE,
    FAMILY,
    MASK_PAIR,
    REREAD_SPLIT,
    TAIL_SPLIT,
    variants,
)

CODE = '''typedef unsigned char u8;
typedef unsigned short u16;
typedef int s32;
typedef struct Cell { struct Cell *next; void *bounds; void *list; } Cell;
s32 hits(void *, s32);
s32 contains(void *);
s32 cellMask(void *);

s32 sweep(u8 *tri, s32 n, Cell *cell, void *list, s32 *base)
{
  s32 i;
  s32 low;
  u16 high;
  s32 temp_v0;
  u8 *p;
  temp_v0 = cellMask(list);
  low = temp_v0 & 0xFF;
  high = temp_v0 & 0xFF00;
  do
  {
    i = 0;
    p = tri + 2;
    do
    {
      if (low & i)
      {
        low = base[i];
        hits(p - 1, low + 4);
        if ((hits(p, low) << 0x18) != 0)
        {
          n++;
        }
      }
      p += 3;
      i++;
    }
    while (i < n);
    loop_9:
    list = cell->list;
    if (contains(list) != 0)
    {
      if ((contains(cell->bounds) << 0x18) != 0)
      {
        cell = cell->next;
        continue;
      }
    }
    cell = cell->next;
    if (cell != NULL)
    {
      goto loop_9;
    }
  } while (list != NULL);
  return high;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def by_family(family):
    return [child for name, child in variants(CODE, 'sweep') if name == family]


def test_a_tested_call_moves_into_a_one_shot_scope():
    children = by_family(CALL_SCOPE)
    assert children
    text = squash(children[0])
    assert 's32 callResult;' in text
    assert 'do { callResult = hits(p, low); } while (0); if ((callResult << 0x18) != 0)' in text


def test_a_name_read_at_the_loop_head_and_reassigned_is_split():
    (child,) = by_family(REREAD_SPLIT)
    text = squash(child)
    assert 'if (low & i) { low_b1 = base[i]; hits(p - 1, low_b1 + 4);' in text
    assert 'hits(p, low_b1)' in text
    assert 's32 low_b1;' in text


def test_the_pointer_step_after_an_if_goes_into_both_arms():
    (child,) = by_family(BIV_ARM)
    assert '{ n++; } p += 3; } else { p += 3; } i++;' in squash(child)


def test_the_walk_becomes_a_loop_with_its_tail_in_the_skipping_arm():
    (child,) = by_family(TAIL_SPLIT)
    text = squash(child)
    assert 'loop_9' not in text
    assert ('for (;;) { list = cell->list; if (!(contains(list) != 0)) { cell = cell->next; if (cell != NULL) '
            '{ continue; } break; }') in text
    assert 'cell = cell->next; break; } cell = cell->next; if (!(cell != NULL)) { break; } } } while (list != NULL);' in text


def test_the_low_half_of_a_mask_pair_is_typed_like_the_high_half():
    (child,) = by_family(MASK_PAIR)
    assert 'u16 low;' in child and 's32 low;' not in child


def test_the_three_that_paid_off_together_are_one_child():
    (child,) = by_family(FAMILY)
    text = squash(child)
    assert 'p += 3; } else { p += 3; }' in text
    assert 'loop_9' not in text
    assert 'u16 low;' in text


def test_the_module_declares_itself():
    assert 'saved_register_cascade' in {repair.module.rsplit('.', 1)[-1] for repair in registry.declared()}

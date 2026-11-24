"""m2c's list walk, sibling loops and a staged pointer base from a large collision sweep."""
import re

from decomprepair import registry
from decomprepair.walk_reentry_repairs import (
    BASE_STAGE,
    COUNTER_MERGE,
    MERGE_PAIR,
    NAME_MERGE,
    WALK,
    WALK_CASCADE,
    variants,
)

CODE = '''typedef unsigned char u8;
typedef unsigned short u16;
typedef int s32;
typedef unsigned int u32;
typedef struct Cell { struct Cell *next; void *bounds; void *list; } Cell;
s32 contains(void *);
s32 hit(void *);

s8 sweep(Cell *cell, void *list, u8 *tris, s32 flag, s32 n, s32 *tab, s32 *idx)
{
  s32 var_s4;
  u16 var_s4_2;
  void *var_s3;
  void *var_s3_2;
  void *temp_a2;
  s32 temp_v1_16;
  s32 temp_a0;
  u8 done;
  done = 0;
  do
  {
    if (flag != 0)
    {
      var_s4 = 0;
      var_s3 = tris + 4;
      do
      {
        hit(var_s3);
        var_s3 += 6;
        var_s4 += 1;
      } while (((u32) (var_s4 & 0xFFFF)) < n);
    }
    else
    {
      var_s4_2 = 0;
      if (var_s4_2 < n)
      {
        var_s3_2 = tris + 2;
        do
        {
          temp_a0 = idx[var_s4_2 * 2];
          if (temp_a0 != 0)
          {
            hit(var_s3_2 - 1);
          }
          var_s3_2 += 3;
          var_s4_2 += 1;
        } while (var_s4_2 < n);
      }
    }
    temp_v1_16 = n; temp_a0 = idx[temp_v1_16 * 2]; temp_a2 = tab[1] + (temp_v1_16 * 6);
    hit(temp_a2);
    loop_9:
    list = cell->list;
    if (contains(list) != 0)
    {
      if (cell == NULL)
      {
        return (s8) done;
      }
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
  return (s8) done;
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def by_family(family):
    return [child for name, child in variants(CODE, 'sweep') if name == family]


def test_the_pointer_base_is_loaded_before_the_index_copy():
    (child,) = by_family(BASE_STAGE)
    assert ('temp_a2 = (void *) tab[1]; temp_v1_16 = n; temp_a2 = (char *) temp_a2 + (temp_v1_16 * 6); '
            'temp_a0 = idx[temp_v1_16 * 2];') in squash(child)


def test_the_locals_of_one_saved_register_become_one_variable():
    child = by_family(NAME_MERGE)[0]
    assert 'var_s3_2' not in child
    assert 'var_s3 = tris + 2;' in child


def test_the_else_loop_counts_with_the_first_loops_counter():
    (child,) = by_family(COUNTER_MERGE)
    text = squash(child)
    assert 'var_s4_2' not in text
    assert 'var_s4 = 0; if (flag < n)' in text
    assert 'idx[(var_s4 & 0xFFFF) * 2]' in text
    assert 'while (((u32) (var_s4 & 0xFFFF)) < n);' in text


def test_the_walk_reenters_a_loop_of_its_own():
    (child,) = by_family(WALK)
    text = squash(child)
    assert 'loop_9:' not in text
    assert ('goto loop_9_walk; loop_9_next: cell = cell->next; if (cell == NULL) continue; loop_9_walk: do { '
            'list = cell->list; if (contains(list) != 0) { if (cell != NULL) { if (!((contains(cell->bounds) << 0x18) '
            '!= 0)) goto loop_9_next; cell = cell->next; break; } else { return (s8) done; } } cell = cell->next; } '
            'while (cell != NULL); } while (list != NULL);') in text


def test_the_measured_pairs_are_offered():
    assert by_family(MERGE_PAIR)
    walked = by_family(WALK_CASCADE)
    assert walked and all('loop_9_walk' in child for child in walked)


def test_the_module_declares_itself():
    assert 'walk_reentry_repairs' in {repair.module.rsplit('.', 1)[-1] for repair in registry.declared()}

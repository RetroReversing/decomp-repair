"""A guard flag reused as the walk's counter, given a sibling walk's counter (a collision sweep, 2798 -> 1384)."""
from decomprepair.flag_counter_split import FAMILY, FAMILY_HOIST, variants

SOURCE = """s32 sweep(Obj *o, u16 *tri, u8 *tri8, s32 n)
{
  u32 flag;
  u16 count;
  s32 hit;
  f32 *p;
  f32 *p2;
  f32 point[3];

  do
  {
    flag = o->flags & 4;
    if (flag)
    {
      hit = 0;
    }
    else
    {
      if (flag < n)
      {
        flag = 0;
        p = &point;
        do
        {
          hit = test(tri, p, flag & 0xFFFF);
          tri += 3;
          flag += 1;
        }
        while ((flag & 0xFFFF) < n);
      }
      count = 0;
      if (count < n)
      {
        p2 = &point;
        do
        {
          hit = test(tri8, p2, count);
          tri8 += 3;
          ++count;
        }
        while (count < n);
      }
    }
    o = o->next;
  }
  while (o != NULL);
  return hit;
}
"""


def by(family):
    return [text for name, text in variants(SOURCE, 'sweep') if name == family]


def test_the_walk_counts_in_the_sibling_counter_and_the_guard_keeps_the_flag():
    plain = by(FAMILY)
    assert plain
    first = plain[0]
    assert 'if (flag < n)' in first
    assert 'count = 0;\n        p = &point;' in first
    assert 'test(tri, p, count & 0xFFFF)' in first and 'count += 1;' in first and '((count & 0xFFFF) < n)' in first
    assert 'flag = 0;' not in first


def test_the_zero_moves_above_the_guard_in_a_second_child():
    moved = [t for t in by(FAMILY) if '      count = 0;\n      if (flag < n)' in t]
    assert moved
    assert '        p = &point;\n        do' in moved[0]


def test_the_hoisted_child_sets_one_address_local_once_before_the_outer_loop():
    hoisted = by(FAMILY_HOIST)
    assert hoisted
    text = hoisted[0]
    assert '  p = &point;\n  do\n' in text
    assert 'p2' not in text
    assert 'test(tri8, p, count)' in text
    assert text.count('p = &point;') == 1


def test_a_flag_read_after_the_walk_is_left_alone():
    source = SOURCE.replace('    o = o->next;', '    use(flag);\n    o = o->next;')
    assert variants(source, 'sweep') == []

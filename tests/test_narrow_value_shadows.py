"""A loop's 16-bit shadow of a value, a copy at the head of an arm, and a wide counter with a narrowed test."""
from decomprepair.narrow_value_shadows import FAMILY_ARM, FAMILY_CAST, FAMILY_COUNTER, FAMILY_RETYPE, variants

# A tile drawer (KMC GCC 2.7.2): `u16 i, j` counters, a position read through `(u16)` twice, two arms that read `x` often.
SAVED = '''void f(s32 ox, s32 oy, Spr *p)
{
  s32 dx, dy;
  u16 i, j;
  s32 x, y, ly;
  for (i = 0; i < p->rows; i++)
  {
    for (j = 0; j < p->cols; j++)
    {
      x = p->x + ox + p->w * i;
      y = p->y + p->h * j;
      if (hires != 0)
      {
        ly = oy + ((u16) y) * 2;
        put(x * 4, ly * 4, (x + p->w) * 4);
      }
      else
      {
        put(x * 4, (((u16) y + oy) * 4), (x + p->w) * 4);
      }
    }
  }
}
'''


def _squash(text):
    return ' '.join(text.split())


def _of(family, source=SAVED):
    return [_squash(src) for fam, src in variants(source, 'f') if fam == family]


def test_the_twice_cast_value_gets_a_u16_shadow_set_right_after_it():
    out = _of(FAMILY_CAST)
    assert len(out) == 1
    assert 'u16 __repair_y_u16;' in out[0]
    assert 'y = p->y + p->h * j; __repair_y_u16 = y;' in out[0]
    assert 'ly = oy + (__repair_y_u16) * 2;' in out[0] or 'ly = oy + __repair_y_u16 * 2;' in out[0]
    assert '(u16) y' not in out[0]


def test_a_value_written_between_the_set_and_the_casts_gets_no_shadow():
    source = SAVED.replace('if (hires != 0)', 'y += 1;\n      if (hires != 0)')
    assert _of(FAMILY_CAST, source) == []


def test_the_arm_that_reads_the_value_twice_starts_with_a_copy_of_it():
    out = _of(FAMILY_ARM)
    assert any('{ __repair_x_arm = x; ly = oy + ((u16) y) * 2; put(__repair_x_arm * 4, ly * 4, (__repair_x_arm + p->w) * 4); }' in s for s in out)
    assert all('s32 __repair_x_arm;' in s for s in out if '__repair_x_arm =' in s)


def test_the_wide_counters_are_children_alone_and_together():
    out = _of(FAMILY_COUNTER)
    assert len(out) == 3
    both = [s for s in out if 's32 i, j;' in s]
    assert both and '(u16) i < p->rows' in both[0] and '(u16) j < p->cols' in both[0]
    assert any('u16 j;' in s and 's32 i;' in s and '(u16) i < p->rows' in s and 'j < p->cols' in s and '(u16) j' not in s for s in out)


def test_no_loop_no_counter_child():
    assert _of(FAMILY_COUNTER, 'void f(void)\n{\n  u16 i;\n  g(i);\n}\n') == []


def test_unknown_function_has_no_children():
    assert variants(SAVED, 'missing') == []


def test_a_wide_local_that_only_holds_sums_is_a_child_declared_u16():
    out = _of(FAMILY_RETYPE)
    assert any('u16 x;' in s and 's32 y, ly;' in s for s in out)
    assert any('u16 y;' in s and 's32 x, ly;' in s for s in out)
    assert all('s16 ' not in s for s in out)


def test_a_local_that_is_stepped_or_has_its_address_taken_keeps_its_type():
    stepped = SAVED.replace('x = p->x + ox + p->w * i;', 'x = p->x + ox + p->w * i;\n      x++;')
    assert not any('u16 x;' in s for s in _of(FAMILY_RETYPE, stepped))
    taken = SAVED.replace('put(x * 4,', 'g(&x); put(x * 4,')
    assert not any('u16 x;' in s for s in _of(FAMILY_RETYPE, taken))


def test_s16_is_offered_when_the_function_casts_to_it():
    source = SAVED.replace('put(x * 4,', 'put((s16) (x * 4),', 1)
    assert any('s16 x;' in s for s in _of(FAMILY_RETYPE, source))

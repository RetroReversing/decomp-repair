from decomprepair.declaration_scope_sink_repairs import ARRAY_FAMILY, FAMILY, variants

SOURCE = """void *spawn(void *arg0, s32 arg1)
{
  u16 len;
  s32 flag;
  void *obj;
  obj = make(0x10);
  flag = arg1 & 1;
  if (obj != NULL)
  {
    len = measure(arg0);
    fill(obj, len);
    use(obj, len);
  }
  return obj;
}
"""


def _sunk(source=SOURCE):
    return [text for family, text in variants(source, 'spawn') if family == FAMILY]


def test_a_local_used_in_one_block_is_declared_at_the_start_of_that_block():
    found = _sunk()
    assert len(found) == 1
    assert found[0].count('u16 len;') == 1
    assert found[0].index('u16 len;') > found[0].index('if (obj != NULL)')
    assert found[0].index('u16 len;') < found[0].index('len = measure')
    assert '  u16 len;\n  s32 flag;' not in found[0]


def test_a_local_used_outside_the_block_or_in_a_loop_stays():
    outside = SOURCE.replace('return obj;', 'return len ? obj : 0;')
    assert not _sunk(outside)
    loop = SOURCE.replace('if (obj != NULL)', 'while (obj != NULL)')
    assert not _sunk(loop)


def test_an_addressed_local_or_a_function_with_asm_is_left_alone():
    assert not _sunk(SOURCE.replace('fill(obj, len);', 'fill(obj, &len);'))
    assert not variants(SOURCE.replace('obj = make(0x10);', 'asm("nop");'), 'spawn')


def test_narrow_locals_come_first():
    source = SOURCE.replace('  s32 flag;\n', '  s32 flag;\n  s32 wide;\n').replace('len = measure(arg0);', 'wide = 3;\n    len = measure(arg0);\n    use(obj, wide);')
    found = _sunk(source)
    assert found[0].index('u16 len;') > found[0].index('if (obj')
    assert 's32 wide;' in found[0].split('if (obj')[0]


ARRAYS = """void draw(u8 *arg0, void *arg1, s32 kind)
{
  volatile u64 padding;
  u8 sp20;
  u8 sp21;
  f32 sp30[3];
  find(arg0, &sp20, &sp21);
  switch (kind)
  {
    case 1:
      break;
    case 2:
      sp30[0] = *(f32 *) (arg0 + 0x24);
      rotate(arg1, sp30);
      break;
  }
}
"""


def _arrays(source=ARRAYS):
    return [text for family, text in variants(source, 'draw') if family == ARRAY_FAMILY]


def test_an_array_used_by_one_switch_body_is_declared_at_its_start():
    found = _arrays()
    assert len(found) == 2
    alone, both = found
    assert alone.index('f32 sp30[3];') > alone.index('switch (kind)')
    assert alone.index('f32 sp30[3];') < alone.index('case 1:')
    assert 'volatile u64 padding;' in alone.split('switch (kind)')[0]
    # the unused volatile scratch moves with it, right after the array: the array's slot must come first
    assert both.index('volatile u64 padding;') == both.index('f32 sp30[3];') + len('f32 sp30[3];\n    ')
    assert both.count('volatile u64 padding;') == 1 and both.index('volatile u64 padding;') > both.index('switch (kind)')


def test_an_array_used_outside_the_block_or_a_source_without_arrays_gets_no_array_variant():
    assert not _arrays(ARRAYS.replace('  switch (kind)', '  sp30[1] = 0;\n  switch (kind)'))
    assert not _arrays(SOURCE)


def test_an_array_in_a_loop_body_stays():
    looped = ARRAYS.replace('  switch (kind)\n  {', '  while (kind--)\n  {').replace('    case 1:\n      break;\n    case 2:\n', '')
    assert not _arrays(looped)


SEGMENT = """s32 segment(Vec3 *a, Vec3 *b, s32 n)
{
  Vec3 v0;
  Vec3 v1;
  Vec3 v2;
  Vec3 v3;
  Vec3 v4;
  Vec3 v5;
  Vec3 v6;
  Vec3 v7;
  Vec3 v8;
  f32 t;
  f32 sign;
  s32 i;
  for (i = 0; i < n; i++)
  {
    t = a[i].x;
    if (t > 0.0f)
    {
      v0 = a[i]; v1 = v0; v2 = v1; v3 = v2; v4 = v3; v5 = v4; v6 = v5; v7 = v6; v8 = v7;
      b[i] = v8;
    }
    else
    {
      sign = -1.0f;
      if (b[i].y < 0.0f)
      {
        sign = 1.0f;
      }
      b[i].z = sign * t;
    }
  }
  return i;
}
"""


def test_scalars_come_before_struct_locals_and_a_for_body_is_a_loop():
    # 7 -> 0 on a 920-instruction SN GCC 2.8.1 function: `sign` declared in its `else` block took its reload slot
    # after the pseudos created before it. Nine struct temporaries filled LIMIT ahead of it.
    found = _sunk_named(SEGMENT, 'segment')
    assert found, 'no child'
    first = found[0]
    assert first.index('f32 sign;') > first.index('else')
    assert first.index('f32 sign;') < first.index('sign = -1.0f;')
    # `t` is used all over the `for` body: moving it into that body is a loop-body sink, never offered
    assert not [text for text in found if 'f32 t;' in text.split('for (i')[1]]


def _sunk_named(source, name):
    return [text for family, text in variants(source, name) if family == FAMILY]

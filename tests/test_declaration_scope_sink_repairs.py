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

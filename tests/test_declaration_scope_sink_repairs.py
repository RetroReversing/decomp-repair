from decomprepair.declaration_scope_sink_repairs import FAMILY, variants

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

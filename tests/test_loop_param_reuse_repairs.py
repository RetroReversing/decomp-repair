from decomprepair import loop_param_reuse_repairs as reuse

SOURCE = '''extern char T[];
void g(u8, u8, u8);
s32 f(s32 arg0, s32 arg1)
{
  s32 result = -1;
  s32 handle;
  s32 idx;
  u32 low;
  handle = h();
  if (handle != -1)
  {
    low = arg1 & 0x7f;
    while (handle != -1) {
    idx = handle & 0xff;
    arg1 = idx * 0x1a0;
    if (*((s32 *) (T + arg1)) != handle)
    {
      return result;
    }
    result = (u8) idx;
    g(0x84, result, T[arg1]);
    g(0x85, result, low & 0xff);
    handle = *((s32 *) (T + (idx * 0x1a0)));
    result = 0;
    }
  }
  return result;
}
'''


def test_offset_moves_to_the_unused_parameter_and_the_pre_loop_local_is_inlined():
    out = [text for _, text in reuse.alias_variants(SOURCE, 'f')]
    assert len(out) == 2
    assert all('arg0 = idx * 0x1a0;' in t and 'T + arg0' in t for t in out)
    assert 'low = arg1 & 0x7f;' in out[0]
    combined = out[1]
    assert 'low = arg1' not in combined and '(arg1 & 0x7f) & 0xff' in combined


def test_a_parameter_read_inside_the_loop_before_its_reuse_is_left_alone():
    source = SOURCE.replace('    idx = handle & 0xff;\n', '    idx = (handle & 0xff) + arg1;\n')
    assert not reuse.alias_variants(source, 'f')
    assert not reuse.alias_variants(SOURCE.replace('s32 arg0, ', ''), 'f')  # no spare parameter


def test_result_copy_that_is_overwritten_before_it_is_read_is_dropped_from_the_calls():
    (_, text), = reuse.temp_variants(SOURCE, 'f')
    assert 'g(0x84, ((u8) idx), T[arg1]);' in text and 'g(0x85, ((u8) idx), low & 0xff);' in text
    assert 'result = (u8) idx;' not in text and 'result = 0;' in text


def test_a_copy_read_elsewhere_than_call_arguments_is_kept():
    assert not reuse.temp_variants(SOURCE.replace('g(0x85, result, low & 0xff);', 'g(0x85, result + 1, low & 0xff);'), 'f')
    assert not reuse.temp_variants(SOURCE.replace('    result = 0;\n', ''), 'f')

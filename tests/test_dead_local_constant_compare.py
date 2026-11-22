from decomprepair.dead_local_constant_compare import FAMILY, variants

SOURCE = """extern s32 D_80107EE0;
extern s32 D_80107EE8;
u32 func(s32 arg0)
{
  s32 index = arg0 & 0xff;
  s32 scaled = (index * 5) << 3;
  u32 result;
  index = *((u8 *) (((s8 *) (&D_80107EE8)) + scaled));
  if (index == 4)
  {
    goto __shared_return_0;
  }
  result = *((u32 *) (((s8 *) (&D_80107EE0)) + scaled));
  if (result == 0)
  {
    __shared_return_0:
    return 0;
  }
  return result >> 31;
}
"""


def test_the_literal_goes_through_the_local_the_next_statement_reloads():
    [(family, revised)] = variants(SOURCE, 'func')
    assert family == FAMILY
    assert '  result = 4;\n  if (index == result)' in revised
    assert revised.count('== 4') == 0 and 'result == 0' in revised


def test_the_local_must_be_dead_at_the_compare():
    # read after the compare before any assignment: not dead
    assert variants(SOURCE.replace('index == 4', 'index == 4 || scaled == 0').replace('  u32 result;',
                    '  u32 result = 3;').replace('  result = *', '  scaled = result; result = *'), 'func') == []
    # the assignment reads the local itself
    assert variants(SOURCE.replace('result = *((u32 *)', 'result = result + *((u32 *)'), 'func') == []
    # a goto lands where the local is read before any return
    jump = SOURCE.replace('    return 0;', '    scaled = result;\n    return 0;')
    assert variants(jump, 'func') == []


def test_a_condition_naming_the_local_loops_and_zero_are_left_alone():
    assert variants(SOURCE.replace('index == 4', 'result == 4'), 'func') == []
    assert variants(SOURCE.replace('index == 4', 'index == 0'), 'func') == []
    assert variants(SOURCE.replace('index == 4', 'index == -1'), 'func') == []
    assert variants(SOURCE.replace('  if (index == 4)', '  while (index == 4)'), 'func') == []
    assert variants(SOURCE.replace('index == 4', 'index == 300').replace('u32 result;', 's8 result;'), 'func') == []


def test_a_local_assigned_inside_an_arm_is_left_alone():
    arm = SOURCE.replace('  result = *((u32 *) (((s8 *) (&D_80107EE0)) + scaled));\n',
                         '  if (scaled)\n  {\n  result = *((u32 *) (((s8 *) (&D_80107EE0)) + scaled));\n  }\n')
    assert variants(arm, 'func') == []

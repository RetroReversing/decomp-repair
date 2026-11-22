from decomprepair.shared_copy_local_split import FAMILY, variants

SOURCE = """void draw(void *arg0, void *arg1, s32 mode)
{
  s32 var_s4;
  s32 temp_v0_2;
  s32 temp_v0_3;
  if (mode == 1)
  {
    temp_v0_2 = find(arg0, 1);
    var_s4 = temp_v0_2;
    use(arg0, var_s4, arg1);
  }
  else
  {
    if (mode == 2)
    {
      temp_v0_3 = find(arg0, 2);
      var_s4 = temp_v0_3;
      use(arg0, var_s4, arg1);
    }
  }
}
"""


def _found(source=SOURCE):
    return [text for family, text in variants(source, 'draw') if family == FAMILY]


def test_each_arms_copy_is_removed_and_its_reads_name_the_call_result():
    found = _found()
    assert len(found) == 1
    out = found[0]
    assert 'var_s4 =' not in out
    assert 'use(arg0, temp_v0_2, arg1);' in out and 'use(arg0, temp_v0_3, arg1);' in out


def test_a_read_outside_every_copys_block_leaves_the_local_alone():
    assert not _found(SOURCE.replace('    if (mode == 2)', '    use(arg0, var_s4, arg1);\n    if (mode == 2)'))


def test_a_single_copy_or_a_call_result_assigned_twice_is_left_alone():
    one = SOURCE.replace('      var_s4 = temp_v0_3;\n', '').replace('use(arg0, var_s4, arg1);\n    }\n  }', 'use(arg0, temp_v0_3, arg1);\n    }\n  }')
    assert not _found(one)
    twice = SOURCE.replace('    temp_v0_2 = find(arg0, 1);\n', '    temp_v0_2 = find(arg0, 1);\n    temp_v0_2 = find(arg0, 3);\n')
    assert not _found(twice)

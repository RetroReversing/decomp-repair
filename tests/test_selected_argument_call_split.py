from decomprepair.selected_argument_call_split import FAMILY, variants

SOURCE = """void f(u8 *arg0, u8 *spare, s32 flags)
{
  u8 *var_a0;
  s32 idx;
  s32 sp29;
  var_a0 = arg0;
  if (flags & 0x1000)
  {
    var_a0 = spare;
  }
  idx = find(var_a0, &sp29, 1);
  use(idx, sp29);
}
"""


def _found(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_call_is_written_in_both_arms_with_each_choice():
    found = _found()
    assert len(found) == 1
    out = found[0]
    assert 'var_a0 =' not in out
    assert out.index('idx = find(spare, &sp29, 1);') < out.index('else') < out.index('idx = find(arg0, &sp29, 1);')
    assert 'if (flags & 0x1000)' in out


def test_a_local_read_elsewhere_or_named_twice_in_the_call_is_left_alone():
    assert not _found(SOURCE.replace('  use(idx, sp29);', '  use(idx, var_a0);'))
    assert not _found(SOURCE.replace('find(var_a0, &sp29, 1)', 'find(var_a0, var_a0, 1)'))

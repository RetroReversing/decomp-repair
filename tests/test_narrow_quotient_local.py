from decomprepair.narrow_quotient_local import FAMILY, variants

SOURCE = """void f(u8 *arg0, s32 *out)
{
  s32 lum;
  s32 var_a1;
  int var_a2;
  unsigned int var_a3;
  var_a1 = arg0[1];
  var_a2 = arg0[2];
  var_a3 = arg0[3];
  lum = ((var_a3 + (var_a1 + var_a2)) / 3) & 0xFFFF;
  out[0] = lum * 5;
}
"""


def _found(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_combined_child_is_first_and_makes_the_operands_signed():
    found = _found()
    assert len(found) == 2
    both, only = found
    assert '  u16 lum;' in both and '  s32 var_a3;' in both and 'unsigned int var_a3' not in both
    assert 'lum = ((var_a3 + (var_a1 + var_a2)) / 3);' in both and '0xFFFF' not in both
    assert '  u16 lum;' in only and 'unsigned int var_a3;' in only


def test_a_mask_that_is_not_a_quotient_or_a_local_assigned_twice_is_left_alone():
    assert not _found(SOURCE.replace('/ 3', '+ 3'))
    assert not _found(SOURCE.replace('  out[0] = lum * 5;', '  lum = 1;\n  out[0] = lum * 5;'))

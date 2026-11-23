"""A word local holding a byte shifted left in place, declared as the halfword."""
from decomprepair import registry
from decomprepair.shifted_byte_temp_narrow import FAMILY, variants

SOURCE = """void pairs(const u8 *q, s32 *out)
{
  u32 xHigh;
  u32 xLow;
  u32 yHigh;
  u32 yLow;
  xHigh = q[0];
  xLow = q[1];
  xHigh <<= 8;
  out[0] = xHigh + xLow;
  yHigh = q[2];
  yLow = q[3];
  yHigh <<= 8;
  out[1] = yHigh + yLow;
}
"""


def test_each_shifted_local_alone_and_all_of_them_are_children():
    children = [child for family, child in variants(SOURCE, 'pairs')]
    assert len(children) == 3
    assert 'u16 xHigh;' in children[0] and 'u32 yHigh;' in children[0] and 'u32 xLow;' in children[0]
    assert 'u32 xHigh;' in children[1] and 'u16 yHigh;' in children[1]
    assert 'u16 xHigh;' in children[2] and 'u16 yHigh;' in children[2] and 'u32 yLow;' in children[2]


def test_a_local_read_elsewhere_or_shifted_further_is_left_alone():
    assert variants(SOURCE.replace('out[0] = xHigh + xLow;', 'out[0] = xHigh + xLow; out[2] = xHigh;'), 'pairs')[0][1].count('u16') == 1
    assert variants(SOURCE.replace('xHigh <<= 8', 'xHigh <<= 12'), 'pairs')[0][1].count('u16') == 1


def test_registry_declares_the_family():
    repair = registry.get('shifted_byte_temp_narrow')
    assert repair is not None and registry.problems(repair) == [] and FAMILY in repair.families

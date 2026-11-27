"""A constant division the target computes unsigned."""
from decomprepair.unsigned_constant_divide import FAMILY, variants

SOURCE = """void spawn(void)
{
  s32 a;
  s32 b;
  a = next(0) % 1800;
  use((f32) a / 2.0f);
  b = next(0) % 1800;
  use(b / 8);  /* a power of two */
}
"""


def test_both_sites_together_first_then_each():
    found = variants(SOURCE, 'spawn', asm='    multu      $v0, $s7\n')
    assert [family for family, _ in found] == [FAMILY] * 3
    assert found[0][1].count('% 1800U;') == 2
    assert 'b / 8' in found[0][1] and '/ 2.0f' in found[0][1]
    assert all(child.count('% 1800U;') == 1 for _, child in found[1:])


def test_only_with_an_unsigned_multiply_or_divide_in_the_target():
    assert variants(SOURCE, 'spawn', asm='    mult       $v0, $s7\n') == []
    assert variants(SOURCE, 'spawn') == []

"""m2c's expansion of an unsigned-to-double conversion."""
from decomprepair.unsigned_double_bias_fold import FAMILY, variants

SOURCE = """void spawn(void)
{
  f64 bias;
  f64 a;
  f64 b;
  s32 v;
  union { s32 value; } w;
  bias = D_80100880;
  v = next(0);
  a = (f64) v;
  if (v < 0) {
    a += bias;
  }
  w.value = next(0);
  b = (f64) w.value;
  if (w.value < 0) {
    b += bias;
  }
  use(a, b);
}
"""

ASM = '    ldc1       $fs1, %lo(D_80100880)($at)\n'


def test_both_sites_together_first_then_each():
    found = variants(SOURCE, 'spawn', asm=ASM)
    assert [family for family, _ in found] == [FAMILY] * 3
    assert 'a = (f64) (u32) v;\n  w.value' in found[0][1]
    assert 'b = (f64) (u32) w.value;\n  use' in found[0][1]
    assert found[0][1].count('+= bias') == 0
    assert all(child.count('+= bias') == 1 for _, child in found[1:])


def test_a_bias_nobody_loaded_is_left_alone():
    assert variants(SOURCE, 'spawn', asm='') == []
    assert variants(SOURCE.replace('+= bias', '+= 1.5'), 'spawn', asm=ASM) == []


def test_the_constant_written_out():
    assert len(variants(SOURCE.replace('+= bias', '+= 4294967296.0'), 'spawn')) == 3

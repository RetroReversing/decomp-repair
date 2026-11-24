"""An equality test of two identifiers written the other way round."""
from decomprepair.equality_operand_swap import FAMILY, variants

SRC = '''void f(s32 x, s32 y)
{
  if (x == y)
  {
    g();
  }
  if (x != 3)
  {
    h();
  }
}
'''


def test_two_identifiers_are_swapped_and_constants_left_alone():
    kids = [src for fam, src in variants(SRC, 'f') if fam == FAMILY]
    assert kids == [SRC.replace('if (x == y)', 'if (y == x)')]

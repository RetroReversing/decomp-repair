"""float_truncation_cast_drop: a float local's integer cast in float code dropped, with the range tests nested."""

from decomprepair import float_truncation_cast_drop as m

SOURCE = """typedef float f32;
typedef int s32;
void hit(void);
f32 f(f32 best, f32 a, f32 b, f32 n)
{
  f32 d;
  f32 y;
  d = a * b;
  y = 0.0f;
  if ((d >= 0.0f) && (((s32) d) < best))
  {
    y = a - (((int) d) * n);
    hit();
  }
  return y;
}
"""


def test_the_combined_child_drops_every_cast_and_nests_the_range_test():
    fam, text = m.variants(SOURCE, 'f')[0]
    assert fam == m.COMBINED
    assert '(s32)' not in text and '(int)' not in text
    assert 'if (d >= 0.0f)\n  {\n    if (d < best)' in text
    assert 'y = a - (d * n);' in text


def test_each_cast_alone_is_a_child():
    singles = [t for fam, t in m.variants(SOURCE, 'f') if fam == m.FAMILY]
    assert any('(s32) d' not in t and '(int) d' in t for t in singles)
    assert any('(int) d' not in t and '(s32) d' in t for t in singles)


def test_a_cast_stored_to_an_integer_stays():
    kept = 'typedef float f32;\nint f(f32 d)\n{\n  int i;\n  i = ((int) d);\n  return i;\n}\n'
    assert m.variants(kept, 'f') == []

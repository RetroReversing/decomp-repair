"""minimum_result_copy: a call result the arms overwrite with smaller candidates, kept apart from the minimum."""

from decomprepair import minimum_result_copy as m

SOURCE = """typedef float f32;
f32 dist(int a);
void hit(void);
void f(int a, int b, int c)
{
  f32 d0;
  f32 d1;
  f32 d2;
  int x;
  d0 = dist(a);
  d1 = dist(b);
  d2 = dist(c);
  x = 1;
  if ((d1 < d0) && (d1 < d2))
  {
    d0 = d1;
  }
  else
  {
    if (d2 < d0)
    {
      d0 = d2;
    }
  }
  if (d0 < 0.04f)
  {
    hit();
  }
}
"""


def test_the_minimum_is_a_local_of_its_own():
    [(fam, text)] = m.variants(SOURCE, 'f')
    assert fam == m.FAMILY
    assert 'd2 = dist(c);\n  x = 1;\n  best_d0 = d0;\n' in text
    assert 'best_d0 = d1;' in text and 'best_d0 = d2;' in text
    assert 'if ((d1 < d0) && (d1 < d2))' in text and 'if (d2 < d0)' in text
    assert 'if (best_d0 < 0.04f)' in text
    assert 'f32 d0;\n  f32 best_d0;' in text


def test_a_variable_set_again_outside_the_arms_is_left_alone():
    again = SOURCE.replace('  x = 1;\n', '  x = 1;\n  d0 = 0.0f;\n')
    assert m.variants(again, 'f') == []

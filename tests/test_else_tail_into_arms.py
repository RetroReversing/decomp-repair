"""The tail after an if/else whose arms end with the same call, written in both arms (a collision query, 5082 -> 4828)."""
from decomprepair.else_tail_into_arms import FAMILY, variants

SOURCE = """s8 query(f32 *pos, f32 *m, f32 *c, s32 *flags, s32 n, s32 k)
{
  u8 hit;
  s32 i;

  hit = 0;
  for (i = 0; i < n; i++)
  {
    if (k)
    {
      c[0] = 1.0f;
      rotate(m, c);
    }
    else
    {
      c[0] = 2.0f;
      rotate(m, c);
    }
    pos[0] += c[0];
    hit = 1;
    *flags |= k;
  }
  return hit;
}
"""


def children(source=SOURCE):
    return [text for family, text in variants(source, 'query') if family == FAMILY]


def test_the_tail_is_written_at_the_end_of_both_arms():
    (child,) = children()
    assert child.count('pos[0] += c[0];') == 2
    assert child.count('hit = 1;') == 2
    assert '      rotate(m, c);\n      pos[0] += c[0];\n      hit = 1;\n      *flags |= k;\n    }\n    else' in child
    assert child.rstrip().endswith('*flags |= k;\n    }\n  }\n  return hit;\n}')


def test_arms_that_end_differently_keep_the_tail():
    assert not children(SOURCE.replace('      c[0] = 2.0f;\n      rotate(m, c);', '      rotate(m, c);\n      c[0] = 2.0f;'))


def test_a_tail_with_a_label_is_not_copied():
    assert not children(SOURCE.replace('    hit = 1;\n', '  done:\n    hit = 1;\n'))


def test_two_joins_also_give_the_child_with_both_copied():
    loop = ('  while (n)\n  {\n    if (k)\n    {\n      f(m);\n      rotate(m, c);\n    }\n    else\n    {\n'
            '      rotate(m, c);\n    }\n    g(c);\n    n--;\n  }\n')
    found = children(SOURCE.replace('  return hit;\n', loop + '  return hit;\n'))
    assert len(found) == 3
    assert any(t.count('hit = 1;') == 2 and t.count('g(c);') == 2 for t in found)


def test_a_tail_that_returns_is_not_copied():
    assert not children(SOURCE.replace('    *flags |= k;\n', '    *flags |= k;\n    return hit;\n'))

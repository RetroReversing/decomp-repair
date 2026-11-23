"""The other polarity of a branch: bit tests, `!` and m2c's goto-tail `if`."""
import re

from decomprepair import branch_polarity_repairs as b

SWAP = '''void f(u16 *p, u8 *q) {
  if (p[0] & 0x10)
  {
    q[0] = 1;
  }
  else
  {
    q[0] = 2;
  }
}
'''
GOTO = '''void f(u16 *p, u8 *q) {
  s32 v;
  v = 255;
  if (p[3])
  {
    if (!(p[0] & 0x10))
    {
      v = 191;
      goto L;
    }
    q[1] = 255;
    q[2] = 255;
  }
  else
  {
    L:
    q[0] = v;
  }
}
'''


def test_negate_any():
    assert b.negate_any('x & 0x10') == '!(x & 0x10)'
    assert b.negate_any('!(x & 0x10)') == 'x & 0x10'
    assert b.negate_any('!flag') == 'flag'
    assert b.negate_any('a < 4') == 'a >= 4'
    assert b.negate_any('a && b') == '!(a && b)'
    # m2c's field macros are reads, not calls
    assert b.negate_any('M2C_FIELD(p, u16 *, 0x42) & 0x10') == '!(M2C_FIELD(p, u16 *, 0x42) & 0x10)'
    assert b.negate_any('f(x)') is None and b.negate_any('i++') is None and b.negate_any('a = b') is None


def test_arms_swapped_where_negate_cannot_invert():
    (_, out), = b.variants(SWAP, 'f')
    assert 'if (!(p[0] & 0x10))' in out
    assert out.index('q[0] = 2;') < out.index('q[0] = 1;')


def test_goto_tail_polarity():
    outs = [out for _, out in b.variants(GOTO, 'f')]
    out = next(o for o in outs if 'if (p[0] & 0x10)' in o)
    assert out.index('q[1] = 255;') < out.index('v = 191;') < out.index('goto L;')
    assert 'else v = 191' not in out and out.count('goto L;') == 1


def test_left_alone():
    # a comparison is `branch_orientation`'s; a call in the condition is evaluated once; a label in the rest stays put
    assert b.variants(SWAP.replace('p[0] & 0x10', 'p[0] == 4'), 'f') == []
    assert b.variants(SWAP.replace('p[0] & 0x10', 'g(p)'), 'f') == []
    assert not any('if (p[0] & 0x10)' in o for _, o in b.variants(GOTO.replace('    q[2] = 255;\n', '    M:\n    q[2] = 255;\n'), 'f'))


LOOPS = '''float g(float);
int f(float t, float u, float *a, int n)
{
  int i;
  int k;
  i = 0;
  do {
    if (g(t) < 1.0f) {
      if (!(t < 0.0f))
      {
        a[0] = t;
        goto next;
      }
      if (a[2] > 0.0f)
      {
        return 1;
      }
      goto next;
    }
    next:
    i++;
  } while (i < n);
  k = 0;
  do {
    if (g(u) < 1.0f) {
      if (!(u < 0.0f))
      {
        a[1] = u;
        goto again;
      }
      if (a[3] > 0.0f)
      {
        return 1;
      }
      goto again;
    }
    again:
    k++;
  } while (k < n);
  return 0;
}
'''


def test_like_shaped_goto_tails_in_two_loops_are_flipped_together_first():
    children = [text for _, text in b.variants(LOOPS, 'f')]
    both = re.sub(r'\s+', ' ', children[0])
    assert 'if (t < 0.0f)' in both and 'if (u < 0.0f)' in both and '!(' not in both
    assert sum(1 for text in children[1:] if '!(t < 0.0f)' not in text and '!(u < 0.0f)' in text) == 1


def test_every_if_is_read_in_a_long_function():
    filler = ''.join('  if (n == %d) { a[0] = %d.0f; }\n' % (i, i) for i in range(30))
    long = LOOPS.replace('  int k;\n', '  int k;\n' + filler, 1)
    assert any('if (t < 0.0f)' in text and 'if (u < 0.0f)' in text for _, text in b.variants(long, 'f'))

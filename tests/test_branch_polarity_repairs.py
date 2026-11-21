"""The other polarity of a branch: bit tests, `!` and m2c's goto-tail `if`."""
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

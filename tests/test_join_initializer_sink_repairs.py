"""A constant assigned before an if and read only after a goto join, moved to the join."""
from decomprepair import join_initializer_sink_repairs as j

SOURCE = '''void f(void *arg0, u16 *p) {
  int c = 0xFF;
  s32 v;
  u16 t;
  v = c;
  if (p[0] & 2)
  {
    t = p[1] + 1;
    p[1] = t;
    if (!(t & 0x10))
    {
      v = 0xBF;
      goto L;
    }
    *((s8 *) (((char *) arg0) + 0x7F)) = c;
  }
  else
  {
    L:
    *((s8 *) (((char *) arg0) + 0x81)) = v;
  }
}
'''


def test_assignment_moves_to_the_label_then_literal_then_unsigned():
    out = [child for _, child in j.variants(SOURCE, 'f')]
    assert len(out) == 3
    sunk, literal, unsigned = out
    assert '  v = c;\n  if' not in sunk and '    v = c;\n    L:' in sunk
    assert '    v = 0xFF;\n    L:' in literal and 'v = 0xBF;' in literal
    assert '(u8 *) (((char *) arg0) + 0x81)) = v;' in unsigned and '(u8 *) (((char *) arg0) + 0x7F)) = 0xFF;' in unsigned


def test_left_alone_when_the_value_is_read_elsewhere():
    # read in the condition, in the then-branch, or after the join
    assert j.variants(SOURCE.replace('if (p[0] & 2)', 'if (v & 2)'), 'f') == []
    assert j.variants(SOURCE.replace('p[1] = t;', 'p[1] = v;'), 'f') == []
    assert j.variants(SOURCE.replace('    *((s8 *) (((char *) arg0) + 0x81)) = v;\n  }\n}', '    *((s8 *) (((char *) arg0) + 0x81)) = v;\n  }\n  p[2] = v;\n}'), 'f') == []
    assert j.variants(SOURCE.replace('goto L;', 'p[3] = 1;'), 'f') == []


def test_join_after_the_statement_without_an_else():
    source = '''void f(u16 *p, u8 *q) {
  s32 v;
  v = 7;
  if (p[0] & 2)
  {
    v = 9;
    goto L;
  }
  p[1] = 0;
  L:
  q[0] = v;
}
'''
    (_, sunk), *_ = j.variants(source, 'f')
    assert '  p[1] = 0;\n  v = 7;\n  L:' in sunk and sunk.count('v = 7;') == 1


def test_mirrored_join_in_the_then_arm_and_a_separated_assignment():
    source = '''void f(u16 *p, u8 *q) {
  s32 v;
  v = 7;
  p[2] = 1;
  if (p[0] & 2)
  {
    L:
    q[0] = v;
  }
  else
  {
    v = 9;
    goto L;
  }
}
'''
    (_, sunk), *_ = j.variants(source, 'f')
    assert '    v = 7;\n    L:' in sunk and '  p[2] = 1;\n  if' in sunk


def test_two_constants_each_sunk():
    source = '''void f(u16 *p, u8 *q) {
  s32 a;
  s32 b;
  a = 1;
  b = 2;
  if (p[0] & 2)
  {
    a = 3;
    b = 4;
    goto L;
  }
  else
  {
    p[1] = 0;
    L:
    q[0] = a;
    q[1] = b;
  }
}
'''
    outs = [c for _, c in j.variants(source, 'f')]
    assert any('    a = 1;\n    b = 2;\n    L:' in c or '    b = 2;\n    a = 1;\n    L:' in c for c in outs)


def test_unsafe_joins_are_left_alone():
    base = '''void f(u16 *p, u8 *q) {
  s32 v;
  v = 7;
  if (p[0] & 2)
  {
    %s
    goto L;
  }
  p[1] = 0;
  L:
  q[0] = v;
}
'''
    assert j.variants(base % 'p[3] = 1;', 'f') == []  # the goto path never assigns V: it would read garbage
    assert j.variants((base % 'v = 9;').replace('  p[1] = 0;', '  if (p[4]) goto L;\n  p[1] = 0;'), 'f') == []  # a second jump to L

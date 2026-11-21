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

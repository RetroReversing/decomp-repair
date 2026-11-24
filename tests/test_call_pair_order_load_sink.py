"""call_pair_order_load_sink: a reader put back after its writer, loads sunk past a call to their use."""

from decomprepair import call_pair_order_load_sink as m

SOURCE = """typedef float f32;
void seg(f32 *out, int a, int b, f32 *p);
f32 dist(f32 *a, f32 *b);
void f(f32 *q1, f32 *q2, f32 *p, int *rec)
{
  int v1;
  int v2;
  f32 d1;
  f32 d2;
  v1 = rec[13];
  seg(q1, v1, v1, p);
  d1 = dist(q1, p);
  v2 = rec[13];
  d2 = dist(q2, p);
  seg(q2, v2, v2, p);
  v1 = rec[13];
  d1 = rec[1];
  seg(q1, 0, 0, p);
  seg(q2, v1, 0, p);
}
"""


def _lines(text):
    return [line.strip() for line in text.split('\n')]


def test_the_reader_goes_after_its_writer_and_the_load_sinks():
    children = m.variants(SOURCE, 'f')
    texts = [t for fam, t in children if fam == m.COMBINED]
    both = [t for t in texts if 'seg(q2, v2, v2, p);\n  d2 = dist(q2, p);' in t]
    assert both
    body = both[0]
    assert '  seg(q1, 0, 0, p);\n  v1 = rec[13];\n  seg(q2, v1, 0, p);' in body


def test_each_step_alone_is_a_child():
    singles = [t for fam, t in m.variants(SOURCE, 'f') if fam == m.FAMILY]
    assert any('seg(q2, v2, v2, p);\n  d2 = dist(q2, p);' in t and 'v1 = rec[13];\n  d1 = rec[1];' in t for t in singles)
    assert any('seg(q1, 0, 0, p);\n  v1 = rec[13];' in t and 'd2 = dist(q2, p);\n  seg(q2' in t for t in singles)


def test_nothing_to_do():
    plain = 'void g(int);\nvoid f(int *r)\n{\n  int v;\n  v = r[1];\n  g(v);\n}\n'
    assert m.variants(plain, 'f') == []

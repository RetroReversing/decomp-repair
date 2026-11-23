"""arm_constants_to_head: constants an arm assigns after its calls, assigned at the head of the arm.

Synthetic shape of a 795-instruction KMC object spawner (5195 -> 4665): three constants set after each arm's calls took
caller-saved registers; set before the calls they cross them and take `$s1 $s2 $s5` like the target."""
from decomprepair import arm_constants_to_head as s

SOURCE = '''void f(s32 id, void *obj) {
  s32 x0, y0, dy;
  void *m;
  setup(obj);
  if (gBorder != 0) {
    put(obj, spawn(1));
    x0 = 0x18;
    y0 = 0x12;
    dy = 3;
    store(obj, x0);
  } else {
    m = mark(id);
    init(m, 0x2B);
    x0 = 0x24;
    y0 = 0x15;
    dy = 6;
  }
  use(obj, x0, y0, dy);
}
'''


def _texts(source=SOURCE):
    return [text for family, text in s.variants(source, 'f') if family == s.FAMILY]


def test_one_arm_alone_and_both_arms_together():
    texts = _texts()
    assert len(texts) == 3
    both = [t for t in texts if t.index('x0 = 0x18;') < t.index('put(obj, spawn(1));')
            and t.index('x0 = 0x24;') < t.index('m = mark(id);')]
    assert len(both) == 1
    assert 'dy = 3;\n    put(obj, spawn(1));' in both[0]


def test_the_first_arm_keeps_its_other_statements_in_order():
    both = max(_texts(), key=lambda t: (t.index('x0 = 0x24;') < t.index('m = mark(id);')))
    assert both.index('store(obj, x0);') > both.index('put(obj, spawn(1));')


def test_a_variable_read_before_its_assignment_stays():
    source = SOURCE.replace('    put(obj, spawn(1));\n', '    put(obj, spawn(y0));\n')
    texts = _texts(source)
    assert all('y0 = 0x12;\n    dy = 3;\n    put' not in t for t in texts)


def test_a_global_is_not_moved():
    source = SOURCE.replace('  s32 x0, y0, dy;\n', '  s32 y0, dy;\n')
    texts = _texts(source)
    assert texts and all(t.index('x0 = 0x18;') > t.index('put(obj, spawn(1));') for t in texts)
    assert all(t.index('x0 = 0x24;') > t.index('init(m, 0x2B);') for t in texts)


def test_no_call_before_the_assignment_means_nothing_to_move():
    source = '''void f(s32 v) {
  s32 x;
  if (v) {
    x = 1;
  } else {
    x = 2;
  }
  g(x);
}
'''
    assert s.variants(source, 'f') == []

"""Copy locals over read-only pointers written at their uses, with the pointers `const` (a 95-instruction plane routine)."""
from decomprepair import const_read_inline as c
from decomprepair import const_read_repairs as r

PLANE = '''s32 plane(Pl *out, V3 *p1, V3 *p2, V3 *p3)
{
  V3 n;
  f32 len;
  f32 py = p1->y;
  f32 pz = p1->z;
  f32 dz1 = p2->z - pz;
  f32 dy1 = p2->y - py;
  f32 dz2 = p3->z - p2->z;
  f32 dy2 = p3->y - p2->y;
  n.x = (dy1 * dz2) - (dz1 * dy2);
  n.y = dz1 * dz2;
  len = g(n.x);
  out->x = n.x;
  out->d = (-out->x) * py - out->y * pz;
  return 1;
}
'''
ALL = '''s32 plane(Pl *out, const V3 *p1, const V3 *p2, const V3 *p3)
{
  V3 n;
  f32 len;
  n.x = ((p2->y - p1->y) * (p3->z - p2->z)) - ((p2->z - p1->z) * (p3->y - p2->y));
  n.y = (p2->z - p1->z) * (p3->z - p2->z);
  len = g(n.x);
  out->x = n.x;
  out->d = (-out->x) * p1->y - out->y * p1->z;
  return 1;
}
'''


def test_every_copy_local_is_inlined_and_the_read_only_pointers_become_const():
    found = c.variants(PLANE, 'plane')
    assert all(family == c.FAMILY for family, _ in found)
    assert found[0][1] == ALL


def test_one_multi_use_difference_can_stay_a_local_in_its_place():
    texts = [t for _, t in c.variants(PLANE, 'plane')]
    kept = [t for t in texts if '  f32 dz1 = p2->z - p1->z;\n' in t]
    assert len(kept) == 1
    assert 'n.y = dz1 * (p3->z - p2->z);' in kept[0]
    assert 'n.x = ((p2->y - p1->y) * (p3->z - p2->z)) - (dz1 * (p3->y - p2->y));' in kept[0]
    assert 'out->d = (-out->x) * p1->y - out->y * p1->z;' in kept[0]
    # the output pointer is written, so it stays plain
    assert all('Pl *out,' in t for t in texts)


def test_nothing_to_inline_without_a_read_only_pointer_or_a_copy_local():
    assert c.variants('void f(V3 *p) {\n  f32 a = p->x;\n  p->y = a;\n  p->z = a;\n}\n', 'f') == []
    assert c.variants('f32 f(const V3 *p) {\n  return p->x;\n}\n', 'f') == []


def test_a_call_in_the_expression_or_a_second_assignment_is_not_a_copy():
    called = 'f32 f(V3 *p) {\n  f32 a = g(p->x);\n  return a + a;\n}\n'
    assert c.variants(called, 'f') == []
    twice = 'f32 f(V3 *p) {\n  f32 a = p->x;\n  a = a + 1.0f;\n  return a + a;\n}\n'
    assert c.variants(twice, 'f') == []


def test_const_read_now_makes_a_struct_pointer_const_when_only_its_fields_are_read():
    texts = [t for _, t in r.variants(PLANE, 'plane')]
    assert texts and 'const V3 *p1, const V3 *p2, const V3 *p3' in texts[0]
    assert 'Pl *out' in texts[0]
    # assigning a field, stepping it or taking its address keeps the pointer plain
    for body in ('p->x = 1.0f;', 'p->x += 1.0f;', 'p->x++;', 'g(&p->x);', 'p->v[2] = 1.0f;'):
        assert r.variants('f32 f(V3 *p) {\n  f32 a = p->y;\n  %s\n  return a;\n}\n' % body, 'f') == []

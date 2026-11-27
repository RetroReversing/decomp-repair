from decomprepair.out_call_into_argument import variants

SOURCE = '''typedef struct { float x, y, z; } V;
void sub(V *, V *, V *);
V cross(V, V);
int side(V, V);
int f(V *a, V *b, V *c) {
  V d, u, v, n;
  int first;
  sub(&d, c, a);
  sub(&u, b, a);
  sub(&v, c, a);
  n = cross(u, v);
  first = side(d, n);
  if (first == 1) {
    sub(&u, c, b);
    sub(&v, a, b);
    n = cross(u, v);
  }
  return first;
}
'''


def test_folds_every_site_and_each_site():
    children = [child for family, child in variants(SOURCE, 'f')]
    assert len(children) == 3
    both = children[0]
    assert 'sub(&d, c, a);\n  n = cross((sub(&u, b, a), u), (sub(&v, c, a), v));' in both
    assert 'n = cross((sub(&u, c, b), u), (sub(&v, a, b), v));' in both
    assert variants(both, 'f') == []


def test_keeps_dependent_helpers_and_the_order_of_calls():
    reads = 'void g(int *, int); void h(int, int); void f(void) { int u, v;\n g(&u, 1);\n g(&v, u);\n h(u, v);\n }'
    assert all('h(u, v);' in child for _, child in variants(reads, 'f'))
    unordered = 'void g(int *); void h(int, int); void f(void) { int u, v;\n g(&v);\n g(&u);\n h(u, v);\n }'
    [(_, child)] = variants(unordered, 'f')
    assert 'g(&v);\n h((g(&u), u), v);' in child

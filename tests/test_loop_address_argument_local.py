"""loop_address_argument_local: a stack array passed to calls in a loop, named in a pointer local before the loop."""

from decomprepair import loop_address_argument_local as m

SOURCE = """typedef float f32;
void seg(f32 *out, f32 *a);
f32 dist(f32 *a, f32 *b);
#define sp158 stack_sp158[0]
#define sp168 stack_sp168[0]
void f(f32 *tri, int n)
{
  f32 stack_sp158[3];
  f32 stack_sp168[3];
  f32 q[3];
  f32 *sp21C;
  int i;
  f32 d;
  i = 0;
  if (n > 0)
  {
    sp21C = &sp158;
    do
    {
      seg(sp21C, tri);
      d = dist(sp21C, q);
      seg(&sp168, tri);
      d += dist(&sp168, q);
      i++;
    }
    while (i < n);
  }
}
"""


def test_the_array_is_named_beside_its_sibling():
    children = m.variants(SOURCE, 'f')
    text = dict(children)[m.FAMILY]
    assert 'sp21C = &sp158;\n    sp168_arg = &sp168;\n    do' in text
    assert 'seg(sp168_arg, tri);' in text and 'dist(sp168_arg, q);' in text
    assert 'f32 *sp168_arg;' in text


def test_an_array_not_in_a_sibling_slot_is_left_out_of_the_combined_child():
    two = SOURCE.replace('seg(&sp168, tri);', 'seg(&sp168, tri);\n      seg(tri, &q);').replace(
        'd += dist(&sp168, q);', 'd += dist(&sp168, q);\n      d += dist(q, &q);')
    children = m.variants(two, 'f')
    assert all(fam == m.FAMILY for fam, _ in children)
    assert any('q_arg' in text for _, text in children)


def test_a_struct_copy_is_not_an_argument():
    copy = SOURCE.replace('seg(&sp168, tri);', '*((f32 *) (&sp168)) = 0;')
    assert all('sp168_arg' not in text for _, text in m.variants(copy, 'f'))


def test_nothing_without_a_loop():
    assert m.variants(SOURCE.replace('do\n', '').replace('while (i < n);', ''), 'f') == []


def test_two_loops_are_named_together_in_one_child():
    loop = SOURCE[SOURCE.index('  i = 0;'):SOURCE.rindex('}')]
    second = loop.replace('sp21C', 'sp214').replace('sp168', 'sp158').replace('&sp158;\n    do', '&sp168;\n    do')
    two = SOURCE.replace('  f32 *sp21C;', '  f32 *sp21C;\n  f32 *sp214;').replace(loop, loop + second)
    fam, text = m.variants(two, 'f')[0]
    assert fam == m.COMBINED
    assert 'seg(sp168_arg, tri);' in text and 'seg(sp158_arg, tri);' in text

"""Two stores of one value through two pointers, as one chained assignment."""
import re

from decomprepair.paired_store_chain import FAMILY, variants

CODE = '''typedef float f32;
typedef struct { f32 *a; f32 *b; f32 x, y; } Rec;
void fill(Rec *r, int n)
{
    int i;
    f32 t;
    for (i = 0; i < n; i++) {
        t = r->x;
        r->b[i] = t;
        r->a[i] = t;
        t = r->y;
        r->b[i + 1] = t;
        r->a[i + 1] = t;
    }
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_each_pair_of_stores_of_one_value_becomes_a_chain():
    children = variants(CODE, 'fill')
    assert [family for family, _ in children] == [FAMILY] * 3
    everything, first, second = (squash(text) for _, text in children)
    assert 'r->a[i] = r->b[i] = t;' in everything and 'r->a[i + 1] = r->b[i + 1] = t;' in everything
    assert 'r->a[i] = r->b[i] = t;' in first and 'r->b[i + 1] = t; r->a[i + 1] = t;' in first
    assert 'r->b[i] = t; r->a[i] = t;' in second and 'r->a[i + 1] = r->b[i + 1] = t;' in second


def test_literals_calls_scalars_and_one_store_are_left_alone():
    assert variants(CODE.replace('= t;', '= 0;'), 'fill') == []
    called = squash(variants(CODE.replace('r->a[i] = t;', 'f(r)->a[i] = t;'), 'fill')[0][1])
    assert 'r->b[i] = t; f(r)->a[i] = t;' in called and 'r->a[i + 1] = r->b[i + 1] = t;' in called
    assert variants('void f(int *p, int v) { int a; int b; a = v; b = v; *p = v; }', 'f') == []
    assert variants(CODE.replace('        r->a[i] = t;\n', '').replace('        r->a[i + 1] = t;\n', ''), 'fill') == []

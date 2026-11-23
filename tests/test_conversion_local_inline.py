"""A float converted to an integer local once, written as the conversion at each use."""
import re

from decomprepair import registry
from decomprepair.conversion_local_inline import FAMILY, variants

CODE = '''typedef int s32;
typedef float f32;
extern void draw(s32, s32, void *);

void f(f32 *p, void *node)
{
    f32 fx;
    f32 fy;
    s32 ix;
    s32 iy;
    fx = p[0] + p[1];
    fy = p[2] + p[3];
    ix = fx;
    iy = fy;
    while (node != 0)
    {
        draw(ix, iy, node);
        node = *(void **) node;
    }
    draw(ix, 0, node);
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_all_the_conversions_at_once_and_each_alone():
    kids = variants(CODE, 'f')
    assert {family for family, _ in kids} == {FAMILY}
    assert len(kids) == 3
    both = squash(kids[0][1])
    assert 's32 ix;' not in both and 'ix = fx;' not in both and 'iy = fy;' not in both
    assert 'draw(((s32) fx), ((s32) fy), node);' in both and 'draw(((s32) fx), 0, node);' in both
    assert 's32 iy;' not in squash(kids[2][1]) and 's32 ix;' in squash(kids[2][1])


def test_an_explicit_cast_keeps_its_type():
    kids = variants(CODE.replace('ix = fx;', 'ix = (s32) fx;'), 'f')
    assert 'draw(((s32) fx)' in squash(kids[0][1])


def test_a_float_that_changes_after_the_conversion_leaves_that_local_alone():
    [(_, child)] = variants(CODE.replace('    while', '    fx = 2.0f;\n    while'), 'f')
    text = squash(child)
    assert 's32 ix;' in text and 'ix = fx;' in text and 'draw(ix, ((s32) fy), node);' in text


def test_a_local_set_twice_or_read_from_a_non_float_is_left_alone():
    [(_, child)] = variants(CODE.replace('iy = fy;', 'iy = fy;\n    iy = 2;'), 'f')
    assert 's32 iy;' in squash(child) and 'draw(((s32) fx), iy, node);' in squash(child)
    assert variants(CODE.replace('ix = fx;', 'ix = p[4];').replace('iy = fy;', 'iy = p[5];'), 'f') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []

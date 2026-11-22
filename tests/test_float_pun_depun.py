"""Float locals written through a float/integer union pun, written as plain floats (a 178-instruction ray and triangle test).

The shape is a synthetic function with the saved source's constructs: the pun locals, the integer array their bits
are stored to, the pun-typed loads through a cast pointer, and the plain float scalars declared after the group.
In the isolated judge the real source went 275 -> 100 (the de-punned locals alone) -> 0 (with the three differences
declared before the loaded components)."""
from decomprepair import float_pun_depun as d

SOURCE = '''typedef struct { f32 x, y, z; } Vec3;
typedef union { f32 f; u32 i; } FU;

s32 test(Vec3 *a, Vec3 *b, Vec3 *c)
{
    Vec3 e1;
    u32 e2[2];
    FU ex, ey, dx, dy;
    f32 dz, e1x, e1y;
    e1x = b->x - a->x;
    e1.x = e1x;
    e1y = b->y - a->y;
    e1.y = e1y;
    ex.f = c->x - a->x;
    e2[0] = ex.i;
    ey.f = c->y - a->y;
    e2[1] = ey.i;
    dz = ((const volatile Vec3 *)b)->z;
    dy = ((FU *)b)[1];
    dx = ((FU *)b)[0];
    return (dy.f * ex.f - dz * ey.f + dx.f) * e1x + e1y > 0.0;
}
'''


def test_every_pun_local_becomes_a_plain_float_and_the_array_a_float_array():
    found = d.variants(SOURCE, 'test')
    assert found and all(family == d.FAMILY for family, _ in found)
    first = found[0][1]
    assert '    f32 ex, ey, dx, dy;\n' in first and '    f32 e2[2];\n' in first
    assert 'e2[0] = ex;' in first and 'dy = ((f32 *)b)[1];' in first
    assert '.f' not in first.split('{', 3)[-1] and '.i;' not in first
    assert first.count('f32 dz, e1x, e1y;') == 1


def test_the_plain_float_locals_declared_later_move_before_the_group_in_every_subset():
    texts = [t for _, t in d.variants(SOURCE, 'test')]
    assert len(texts) == 1 + 7
    moved = [t for t in texts if '    f32 e1x, e1y;\n    f32 ex, ey, dx, dy;\n    f32 dz;\n' in t]
    assert moved


def test_a_pun_used_any_other_way_is_left_alone():
    other = SOURCE.replace('return (', 'return ex.i + (')
    texts = [t for _, t in d.variants(other, 'test')]
    assert texts and all('FU ex' in t or 'FU ex,' in t or 'FU ex;' in t for t in texts)
    assert all('f32 dx, dy;' in t or 'f32 ey, dx, dy;' in t for t in texts)


def test_a_source_without_a_pun_gives_nothing():
    assert d.variants('s32 f(f32 *p) { f32 x; x = p[0]; return x > 0.0; }', 'f') == []

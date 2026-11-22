"""Vector fields kept in scalar locals: a local record's fields staged and a pointer's repeated reads cached.

A synthetic cross-product function with the constructs of the 178-instruction ray and triangle test: a local record
written field by field and read back, and a direction vector read twice per component. In the isolated judge the real
function went 7935 -> 650 with the staged differences and the direction read through a volatile pointer, and 0 after
two `allocation_lever` statement moves."""
from decomprepair import field_scalar_stage as s

SOURCE = '''typedef struct { f32 x, y, z; } Vec3;
s32 cross(Vec3 *a, Vec3 *d, Vec3 *c, f32 *out)
{
    Vec3 e, p;
    f32 det;
    e.x = a->x - c->x;
    e.y = a->y - c->y;
    e.z = a->z - c->z;
    p.x = d->y * e.z - d->z * e.y;
    p.y = d->z * e.x - d->x * e.z;
    p.z = d->x * e.y - d->y * e.x;
    det = e.x * p.x + e.y * p.y + e.z * p.z;
    if (det < 1e-10f) return 0;
    *out = d->x * det;
    return 1;
}
'''


def _texts(source=SOURCE):
    found = s.variants(source, 'cross')
    assert all(family == s.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_staged_record_and_the_cached_reads_are_one_child():
    both = [t for t in _texts() if 'e_x = a->x - c->x;\n    e.x = e_x;' in t and 'd_z = ((const volatile Vec3 *)d)->z;' in t]
    assert both
    assert any('    p.x = d_y * e_z - d_z * e_y;\n' in t for t in both)


def test_each_edit_is_also_offered_alone():
    texts = _texts()
    assert any('d_x' not in t and 'e_x = ' in t for t in texts)
    assert any('e_x' not in t and 'd_x = d->x;' in t for t in texts)


def test_the_declarations_go_after_the_existing_ones_in_either_order():
    texts = _texts()
    assert any('    f32 e_x, e_y, e_z;\n    f32 d_x, d_y, d_z;\n' in t for t in texts)
    assert any('    f32 d_x, d_y, d_z;\n    f32 e_x, e_y, e_z;\n' in t for t in texts)


def test_a_store_through_a_pointer_before_the_last_read_blocks_the_cache():
    blocked = SOURCE.replace('    e.x = a->x - c->x;\n', '    *out = 1.0f;\n    e.x = a->x - c->x;\n')
    assert all('d_x = d->x;' not in t for t in _texts(blocked))


def test_a_function_with_blocks_is_left_alone():
    looped = SOURCE.replace('    det = ', '    while (det) { det = 0; }\n    det = ')
    assert s.variants(looped, 'cross') == []

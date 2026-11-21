"""A float field both arms recompute: updated in place, with one float local used in both arms."""
from decomprepair import float_arm_roles as roles

SOURCE = '''typedef struct { f32 x, y, z; } Vec;
extern f64 K;
void f(void *obj, s32 kind, f32 limit, f32 y) {
    Vec dir;
    f32 old;
    f32 r;

    g(&dir);
    if (kind == 2) {
        r = (limit - y) * 30.0f;
        old = M2C_FIELD(obj, f32 *, 0xCC);
        r = (f32)((f64)(r - old) * K + (f64)old);
    } else {
        h(obj);
        r = dir.y * 14.999999f;
    }
    M2C_FIELD(obj, f32 *, 0xCC) = r;
    M2C_FIELD(obj, f32 *, 0x28) = limit;
}
'''
FIELD = 'M2C_FIELD(obj, f32 *, 0xCC)'
UPDATED = f'''        r = (limit - y) * 30.0f;
        {FIELD} += (f64)(r - {FIELD}) * K;
    }} else {{
        h(obj);
'''


def test_both_rewrites_come_first_then_each_alone():
    # An 836-instruction N64 function, six $f0/$f2 operands from exact: 30 -> 15 with the update, 0 with both.
    (both, exact), (update, partial) = roles.variants(SOURCE, 'f')
    assert (both, update) == ('float_arm_roles', 'float_arm_update')
    assert UPDATED + f'        r = dir.y;\n        {FIELD} = r * 14.999999f;\n    }}\n    M2C_FIELD(obj, f32 *, 0x28) = limit;' in exact
    assert UPDATED + f'        {FIELD} = dir.y * 14.999999f;\n    }}\n    M2C_FIELD(obj, f32 *, 0x28) = limit;' in partial
    assert 'old =' not in exact and '    f32 old;\n' in exact  # the copy had no reader left; a declaration costs nothing


def test_the_shared_local_alone_on_a_source_already_storing_in_each_arm():
    _, partial = roles.variants(SOURCE, 'f')[1]
    (family, out), = roles.variants(partial, 'f')
    assert family == 'float_arm_shared_local'
    assert out == roles.variants(SOURCE, 'f')[0][1]


def test_addition_sides_and_precision_are_kept():
    plain = SOURCE.replace('(f32)((f64)(r - old) * K + (f64)old)', 'old + (r - old) * 0.5f')
    assert f'{FIELD} += (r - {FIELD}) * 0.5f;' in roles.variants(plain, 'f')[0][1]
    # a double sum of two floats is not a float sum, and `old + a + b` is not `old + (a + b)`
    for rhs in ('(f32)((r - old) * 0.5f + (f64)old)', 'old + r + 1.0f', 'old - r', 'old * r'):
        changed = SOURCE.replace('(f32)((f64)(r - old) * K + (f64)old)', rhs)
        assert rhs in changed and not roles.variants(changed, 'f')


def test_left_alone_when_the_result_or_the_field_is_not_plain():
    assert not roles.variants(SOURCE.replace('    f32 r;', '    s32 r;'), 'f')
    assert not roles.variants(SOURCE.replace('= limit;\n}', '= limit + r;\n}'), 'f')  # read after the store
    assert not roles.variants(SOURCE.replace('    f32 r;', '    volatile f32 r;'), 'f')
    moved = SOURCE.replace('        old = M2C_FIELD(obj, f32 *, 0xCC);\n', '')
    moved = moved.replace('    if (kind == 2) {\n', '    old = M2C_FIELD(obj, f32 *, 0xCC);\n    if (kind == 2) {\n')
    assert 'old = M2C' in moved and not roles.variants(moved, 'f')  # g/h may write the field in between


def test_the_shared_local_only_copies_a_float():
    partial = roles.variants(SOURCE, 'f')[1][1]
    assert not roles.variants(partial.replace('f32 x, y, z;', 's32 x, y, z;'), 'f')
    assert not roles.variants(partial.replace('dir.y * 14', 'next(obj) * 14'), 'f')
    used = partial.replace('= limit;\n}', '= limit;\n    r = 0.0f;\n}')
    assert not roles.variants(used, 'f')  # the local is someone else's too

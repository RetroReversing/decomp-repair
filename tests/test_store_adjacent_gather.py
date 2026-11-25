"""store_adjacent_gather: a store to the next field of a record stands beside the store before it."""
from decomprepair import registry
from decomprepair import store_adjacent_gather as gather

SOURCE = '''typedef struct Obj {
    s32 id;
    f32 x;
    f32 y;
    f32 z;
    s32 f10;
    s32 f14;
    void *f18;
} Obj;
void *spawn(Obj *a, s32 d[3]);
void *func_spawn(Obj *a, s32 *d) {
    Obj *o;

    o = spawn(a, d);
    o->x = a->x + (f32) d[0];
    o->y = a->y + (f32) d[1];
    o->f10 = 0x64;
    o->f14 = 0;
    o->f18 = &spawn;
    o->z = a->z + (f32) d[2];
    return o;
}
'''


def test_z_moves_directly_after_y_past_the_constant_stores():
    out = gather.variants(SOURCE, 'func_spawn')
    assert out and {family for family, _ in out} == {gather.FAMILY}
    wanted = SOURCE.replace('    o->z = a->z + (f32) d[2];\n', '').replace(
        '    o->f10 = 0x64;\n', '    o->z = a->z + (f32) d[2];\n    o->f10 = 0x64;\n')
    assert wanted in [child for _, child in out]


def test_offsets_from_m2c_fields_and_a_stored_value_the_move_would_change_are_handled():
    source = '''void *g(void *a, s32 n);
void *f(void *a, s32 n) {
    void *o;

    o = g(a, n);
    M2C_FIELD(o, f32 *, 4) = n;
    M2C_FIELD(o, s32 *, 0x10) = 1;
    M2C_FIELD(o, s32 *, 0x14) = 2;
    M2C_FIELD(o, f32 *, 8) = n;
    return o;
}
'''
    out = [child for _, child in gather.variants(source, 'f')]
    assert any(child.index('f32 *, 8)') < child.index('s32 *, 0x10)') for child in out)


def test_a_pointer_that_may_alias_keeps_its_order():
    source = SOURCE.replace('    o = spawn(a, d);\n', '    o = a;\n')
    assert not [c for _, c in gather.variants(source, 'func_spawn') if c.index('o->z') < c.index('o->f10')]


def test_nothing_without_a_run_and_the_registry_declares_it():
    assert gather.variants('void f(void) {\n    g();\n}\n', 'f') == []
    mine = [repair for repair in registry.declared() if repair.module == 'store_adjacent_gather']
    assert mine and gather.FAMILY in mine[0].families
    assert not registry.problems(mine[0])

from decomprepair.argument_comma_store import variants

SOURCE = '''typedef struct { short x; short y; char pad[8]; char state; } Obj;
short turn(int, int);
void f(Obj *p) {
    short angle;
    p->state = 5;
    angle = turn(p->x, p->y);
    p->x = angle;
}
'''


def test_the_store_goes_into_each_argument_last_first():
    children = [child for family, child in variants(SOURCE, 'f')]
    assert 'angle = turn(p->x, (p->state = 5, p->y));' in children[0]
    assert 'angle = turn((p->state = 5, p->x), p->y);' in children[1]
    assert '    p->state = 5;\n' not in children[0]


def test_m2c_fields_must_not_overlap():
    source = '''int g(int);
void f(void *a) {
    M2C_FIELD(a, s32 *, 0x10) = 0;
    g(M2C_FIELD(a, s16 *, 0x12));
}
'''
    assert variants(source, 'f') == []
    assert len(variants(source.replace('0x12', '0x14'), 'f')) == 1


def test_a_global_argument_another_base_or_a_computed_value_is_left_alone():
    assert variants(SOURCE.replace('turn(p->x, p->y)', 'turn(p->x, other)'), 'f') == []
    assert variants(SOURCE.replace('turn(p->x, p->y)', 'turn(p->x, q->y)'), 'f') == []
    assert variants(SOURCE.replace('turn(p->x, p->y)', 'turn(p->x, p->state)'), 'f') == []
    assert variants(SOURCE.replace('p->state = 5;', 'p->state = g();'), 'f') == []

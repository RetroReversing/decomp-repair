from decomprepair import sunk_store_pair_order

SOURCE = '''void f(Obj *obj) {
    Rec *p;
    s32 color;

    p = alloc();
    p->x += cosine(obj->angle);
    *(s32 *)((char *)p + 0x38) = 0x20;
    p->y -= sine(obj->angle);
    color = obj->shade;
    p->timer = 0x25A;
    p->flag = 1;
    p->type = 0;
    p->owner = obj->owner;
    p->kind = 2;
}
'''

# the constant store below the second call and the pair (owner, kind) above (flag, type), together
WANTED = SOURCE.replace('''    *(s32 *)((char *)p + 0x38) = 0x20;
''', '').replace('''    p->flag = 1;
    p->type = 0;
    p->owner = obj->owner;
    p->kind = 2;''', '''    *(s32 *)((char *)p + 0x38) = 0x20;
    p->owner = obj->owner;
    p->kind = 2;
    p->flag = 1;
    p->type = 0;''')


def lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def test_sinks_the_constant_and_moves_the_pair_in_one_child():
    children = sunk_store_pair_order.variants(SOURCE, 'f')
    assert lines(WANTED) in [lines(child) for family, child in children if family == 'sunk_store_pair_order']


def test_pair_move_alone():
    children = sunk_store_pair_order.variants(SOURCE, 'f')
    assert any(family == 'store_pair_move' for family, _ in children)
    for _, child in children:
        assert sorted(lines(child)) == sorted(lines(SOURCE))


def test_constant_stays_above_a_call_that_takes_its_record():
    source = SOURCE.replace('sine(obj->angle)', 'sine(p)')
    assert not [child for family, child in sunk_store_pair_order.variants(source, 'f')
                if family == 'sunk_store_pair_order']


def test_constant_stays_above_a_read_of_its_field():
    source = SOURCE.replace('color = obj->shade;', 'color = *(s32 *)((char *)p + 0x38);')
    for family, child in sunk_store_pair_order.variants(source, 'f'):
        if family == 'sunk_store_pair_order':
            assert child.index('p + 0x38) = 0x20') < child.index('color = ')


def test_dependent_stores_never_pass_each_other():
    source = '''void f(Rec *p) {
    p->a = 1;
    p->b = p->a;
    p->c = p->b;
}
'''
    assert sunk_store_pair_order.variants(source, 'f') == []

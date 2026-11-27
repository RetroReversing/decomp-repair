"""A table element indexed again in each of a run of statements, read through one pointer local."""
from decomprepair import repeated_element_pointer as module

SOURCE = '''extern Obj objects[];
extern Slot slots[];

void f(Trail *tr, Obj *o)
{
    f32 dx, dy;

    dx = objects[slots[tr->target].idx].x - o->x;
    dy = objects[slots[tr->target].idx].y - o->y;
    h(dx, dy);
}
'''


def _children(source=SOURCE):
    return [text for _family, text in module.variants(source, 'f')]


def test_the_run_reads_one_element_pointer_in_both_places():
    out = _children()
    scoped, at_head = out[0], out[1]
    assert '        Obj *element = &objects[slots[tr->target].idx];\n' in scoped
    assert 'dx = element->x - o->x;' in scoped and 'dy = element->y - o->y;' in scoped
    assert '{\n    Obj *element;\n' in at_head and '    element = &objects[slots[tr->target].idx];\n' in at_head


def test_member_stores_through_a_local_index_are_one_run():
    source = 'extern Obj objects[];\nvoid f(s32 e)\n{\n    s32 k;\n\n    objects[e].x = 1;\n    objects[e].y = 2;\n}\n'
    assert 'element->x = 1;' in _children(source)[0] and 'element->y = 2;' in _children(source)[0]


def test_an_index_that_can_change_inside_the_run_is_left_alone():
    call = SOURCE.replace('- o->y;', '- g();')
    assert not any('element->y' in t for t in _children(call))
    stored = 'extern Obj objects[];\nextern s32 n;\nvoid f(Obj *o)\n{\n    objects[n].x = 1;\n    objects[n].y = 2;\n}\n'
    assert _children(stored) == []
    assigned = 'extern Obj objects[];\nvoid f(s32 e)\n{\n    e = objects[e].x;\n    e = objects[e].y;\n}\n'
    assert _children(assigned) == []

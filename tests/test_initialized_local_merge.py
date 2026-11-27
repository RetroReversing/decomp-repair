from decomprepair import initialized_local_merge as module

SOURCE = """void f(Obj *obj)
{
    s32 state = obj->state;

    if (state == 1) {
        Cam *cam = &cams[obj->id];
        u16 h = start(state, cam->x);
        s32 i;

        stop(h);
        for (i = 0; i < 3; i++) {
            u16 h2;
            h2 = start(i, cam->x);
            stop(h2);
        }
    }
}
"""


def test_split_keeps_the_order_of_the_initialisers():
    plain = module.split(SOURCE, 'f')
    assert 's32 state;\n    state = obj->state;' in plain
    assert plain.index('cam = &cams[obj->id];') < plain.index('h = start(state, cam->x);') < plain.index('stop(h);')
    assert plain.index('s32 i;') < plain.index('cam = &cams[obj->id];')


def test_the_two_handles_become_one():
    children = [child for _, child in module.variants(SOURCE, 'f')]
    assert any('h2' not in child and 'h = start(i, cam->x);' in child for child in children)


def test_nothing_to_split_gives_nothing():
    assert module.variants('void f(void)\n{\n    u16 a;\n    u16 b;\n    a = g();\n    h(a);\n    b = g();\n    h(b);\n}\n', 'f') == []

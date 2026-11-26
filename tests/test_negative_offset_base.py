"""A pointer used only below itself gets a second pointer at its lowest place."""
from decomprepair import negative_offset_base as n
from decomprepair import registry

INIT = '''void f(u8 v) {
    u8 *p = D_80000104;

    p[-4] = v;
    p[-3] = v;
    p[0] += 1;
}
'''
LATE = '''void f(u8 v) {
    u8 *p;
    s32 i;

    p = D_80000104;
    i = p[0];
    p[-2] = i;
    p[-1] = v;
}
'''


def test_initialised_pointer():
    [(family, out)] = n.variants(INIT, 'f')
    assert family == n.FAMILY
    assert 'u8 *p = D_80000104;\n    u8 *p_head = p - 4;' in out
    assert 'p_head[0] = v;' in out and 'p_head[1] = v;' in out and 'p[0] += 1;' in out


def test_assigned_pointer():
    [(_, out)] = n.variants(LATE, 'f')
    assert 'u8 *p;\n    u8 *p_head;' in out
    assert 'p = D_80000104;\n    p_head = p - 2;' in out
    assert 'p_head[0] = i;' in out and 'p_head[1] = v;' in out


def test_moving_pointer_is_left():
    assert n.variants(INIT.replace('p[0] += 1;', 'p++;'), 'f') == []
    assert n.variants(LATE.replace('i = p[0];', 'p += 4;'), 'f') == []
    assert n.variants('void f(u8 *p) {\n    p[-1] = 0;\n}\n', 'f') == []


def test_declared_to_the_registry():
    assert any(r.module == 'negative_offset_base' for r in registry.declared())

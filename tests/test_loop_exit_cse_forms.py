from decomprepair import loop_exit_cse_forms as forms

SOURCE = '''void f(Obj *obj)
{
    u16 i;
    u16 a;
    u16 id;
    u16 v;

    i = 0;
    id = table[n].rows[i].id;
    while (id != 0xFF) {
        obj->points[id] = table[n].rows[i].x;
        i++;
        id = table[n].rows[i].id;
    }
    a = 0;
    do {
        v = get(a);
        if (v >= i) {
            obj->times[i] = a;
            i++;
        }
        a += 4;
    } while (a < 0x3D && i < 0x10);
}
'''


def children(source, family):
    return [child for label, child in forms.variants(source, 'f') if label == family]


def test_loop_and_break():
    [child] = children(SOURCE, forms.AND_BREAK)
    assert 'if (!(a < 0x3D)) {\n            break;\n        }\n    } while (i < 0x10);' in child


def test_loop_test_assignment():
    [child] = children(SOURCE, forms.ASSIGN)
    assert 'i = 0;\n    while ((id = table[n].rows[i].id) != 0xFF) {' in child
    assert 'i++;\n    }\n    a = 0;' in child


def test_arm_head_loop_note():
    [child] = children(SOURCE, forms.NOTE)
    assert 'if (v >= i) {\n            do { } while (0);\n            obj->times[i] = a;' in child


def test_combined_has_all_three():
    [child] = children(SOURCE, forms.COMBINED)
    for text in ('while ((id = table[n].rows[i].id) != 0xFF)', 'if (!(a < 0x3D))', 'do { } while (0);'):
        assert text in child


def test_declines():
    source = '''void f(void)
{
    x = read(0);
    while (x != 0) {
        x = read(1);
    }
    do {
        if (y) {
            continue;
        }
    } while (a && b || c);
}
'''
    assert forms.variants(source, 'f') == []

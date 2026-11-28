"""A copy every path through an `if` tree makes (m2c's delay-slot copies) written once after the tree."""
from decomprepair import path_copy_hoist as p

SOURCE = '''void f(Obj *obj) {
    u8 kind;
    Obj *cursor;

    kind = obj->kind;
    if (kind != 1) {
        if ((s32) kind < 2) {
            cursor = obj;
            if (kind == 0) {
                start(obj);
            }
        } else {
            cursor = obj;
            if (kind == 2) {
                update(obj);
                cursor = obj;
            }
        }
    } else {
        if (obj->owner == 0) {
            A = 0;
            goto block_9;
        }
        if (obj->owner == kind) {
            B = 0;
            goto block_9;
        }
        cursor = obj;
        if (obj->owner == 2) {
            C = 0;
block_9:
            cursor = obj;
        }
    }
    walk(cursor);
}
'''


def test_the_copy_follows_the_tree_and_the_tree_is_a_switch():
    out = p.variants(SOURCE, 'f')
    family, first = out[0]
    assert family == p.SWITCH
    assert first.count('cursor = obj;') == 1
    assert first.index('cursor = obj;') > first.index('switch (kind)')
    assert 'case 0:' in first and 'case 1:' in first and 'case 2:' in first and 'goto' not in first
    assert any(f == p.HOIST and text.count('cursor = obj;') == 1 for f, text in out)


def test_declined_when_a_path_keeps_the_old_value():
    source = '''void f(Obj *obj) {
    Obj *cursor;

    cursor = 0;
    if (a) {
        cursor = obj;
    } else if (b) {
        cursor = obj;
    }
    walk(cursor);
}
'''
    assert p.variants(source, 'f') == []
    # the tree reads the copy, or changes what was copied
    both = source.replace('} else if (b) {\n        cursor = obj;', '} else {\n        cursor = obj;')
    assert p.variants(both, 'f')
    assert p.variants(both.replace('if (a) {', 'if (cursor == 0) {'), 'f') == []
    assert p.variants(both.replace('if (a) {\n', 'if (a) {\n        obj = 0;\n'), 'f') == []

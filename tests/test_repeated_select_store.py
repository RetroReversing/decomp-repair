"""A test repeated to pick a value stored once, written as the one `if`/`else` store it came from."""
from decomprepair import registry
from decomprepair import repeated_select_store as p

FENCED = '''void tick(Obj *obj)
{
    s32 step;

    step = -5;
    do { if (obj->mode == 1) {
        if (obj->kind == 0xFFFF) {
            return;
        }
        spawn(obj);
        step = -5;
        if (obj->mode == 1) {
            step = 5;
        }
    } } while (0);
    do { obj->step = step; } while (0);
    move(obj);
}
'''

LABELLED = '''void tick(void *obj)
{
    s32 value;
    s32 kind;

    value = -5;
    if (M2C_FIELD(obj, s32 *, 4) == 1) {
        kind = M2C_FIELD(obj, s32 *, 8);
        if (kind != 0) {
            spawn(obj);
            value = -5;
            if (M2C_FIELD(obj, s32 *, 4) == 1) {
                value = 5;
            }
            goto block_3;
        }
    } else {
block_3:
        M2C_FIELD(obj, s32 *, 0xC) = value;
        move(obj);
    }
}
'''


def test_the_two_stores_follow_the_guard_and_the_fences_go():
    out = dict(p.variants(FENCED, 'tick'))
    text = out[p.FAMILY]
    assert 'step;' not in text.replace('obj->step', '') and 'step = -5;\n    if' not in text
    assert 'while (0)' not in text
    assert ('        spawn(obj);\n    }\n    if (obj->mode == 1) {\n        obj->step = 5;\n    } else {\n'
            '        obj->step = -5;\n    }\n    move(obj);') in text
    assert 'do {\n        if (obj->mode == 1) {' in out[p.FENCED_FAMILY]
    assert '} while (0);\n    if (obj->mode == 1) {\n        obj->step = 5;' in out[p.FENCED_FAMILY]


def test_an_unfenced_guard_gives_one_child():
    plain = FENCED.replace('do { if', 'if').replace('} } while (0);', '}').replace(
        'do { obj->step = step; } while (0);', 'obj->step = step;')
    assert [family for family, _ in p.variants(plain, 'tick')] == [p.FAMILY]


def test_the_labelled_store_in_the_outer_else():
    [(family, text)] = p.variants(LABELLED, 'tick')
    assert family == p.FAMILY
    assert 'goto' not in text and 'block_3' not in text and 's32 value;' not in text
    assert ('        kind = M2C_FIELD(obj, s32 *, 8);\n        if (kind == 0) {\n            return;\n        }\n'
            '        spawn(obj);\n    }\n    if (M2C_FIELD(obj, s32 *, 4) == 1) {\n'
            '        M2C_FIELD(obj, s32 *, 0xC) = 5;\n    } else {\n        M2C_FIELD(obj, s32 *, 0xC) = -5;\n    }\n'
            '    move(obj);\n}') in text


def test_declines_when_the_meaning_would_change():
    for source in (
        FENCED.replace('obj->mode == 1) {\n            step = 5', 'obj->mode == 2) {\n            step = 5'),
        FENCED.replace('obj->mode == 1', 'check(obj) == 1'),
        FENCED.replace('move(obj);', 'move(step);'),
        FENCED.replace('spawn(obj);', 'spawn(step);'),
        FENCED.replace('spawn(obj);\n        step = -5;', 'spawn(obj);\n        step = -6;'),
        FENCED.replace('return;', 'break;'),
    ):
        assert p.variants(source, 'tick') == [], source
    # a function with a result: falling off the guard is not the same as the early return
    assert p.variants(LABELLED.replace('void tick', 's32 tick'), 'tick') == []


def test_declared():
    assert any(repair.module == 'repeated_select_store' for repair in registry.declared())


def test_a_default_that_is_not_set_again_must_be_a_constant():
    once = FENCED.replace('spawn(obj);\n        step = -5;', 'spawn(obj);')
    assert [family for family, _ in p.variants(once, 'tick')][0] == p.FAMILY
    assert p.variants(once.replace('step = -5;', 'step = obj->base;'), 'tick') == []

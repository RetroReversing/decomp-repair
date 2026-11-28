"""`v = obj->kind; switch (v)` written back as `switch (obj->kind)`."""
from decomprepair import switch_selector_inline as s

SOURCE = '''typedef struct Obj {
    u8 kind;
    u8 owner;
} Obj;

void f(Obj *obj) {
    u8 sel;

    if (obj->kind == 9) {
        return;
    }
    sel = obj->kind;
    switch (sel) {
        case 0:
            start(obj);
            break;
        case 1:
            if (obj->owner == sel) {
                gDone = 0;
            }
            break;
    }
}
'''


def test_the_switch_takes_the_expression_and_arms_the_value():
    [(family, out)] = s.variants(SOURCE, 'f')
    assert family == s.FAMILY
    assert 'switch (obj->kind) {' in out and 'if (obj->owner == 1) {' in out
    assert 'sel = ' not in out


def test_declined_when_the_local_matters():
    assert s.variants(SOURCE.replace('obj->kind;\n    switch', 'pick(obj);\n    switch'), 'f') == []  # a call
    assert s.variants(SOURCE.replace('    }\n}\n', '    }\n    use(sel);\n}\n'), 'f') == []  # read after the switch
    assert s.variants(SOURCE.replace('start(obj);\n            break;', 'start(obj);'), 'f') == []  # falls into the read
    assert s.variants(SOURCE.replace('gDone = 0;', 'sel = 2;'), 'f') == []  # written twice
    assert s.variants(SOURCE.replace('u8 kind;', 's32 kind;'), 'f') == []  # the local narrows the value

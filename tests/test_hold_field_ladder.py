from decomprepair.hold_field_ladder import variants

SOURCE = '''typedef struct { s32 error; s32 kind; } Pak;
extern Pak slots[];
void f(s32 i) {
    if (slots[i].error == 5) { found(); }
    else if (slots[i].error != 0) { bad(); }
    else { okay(); }
}
'''


def test_holds_the_field_for_both_checks():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert text.count('slots[i].error') == 1
    assert 'if (__repair_held_error == 5)' in text
    assert 'else if (__repair_held_error != 0)' in text


def test_rejects_volatile_macros_and_changed_access():
    assert not variants(SOURCE.replace('s32 error;', 'volatile s32 error;'), 'f')
    assert not variants(SOURCE, 'f', '#define error other')
    assert not variants(SOURCE.replace('slots[i].error != 0', 'slots[j].error != 0'), 'f')
    assert not variants(SOURCE.replace('extern Pak slots[];', 'extern volatile Pak slots[];'), 'f')


def test_does_not_move_load_outside_unbraced_conditional():
    assert not variants(SOURCE.replace('if (slots[i].error == 5)', 'if (i) if (slots[i].error == 5)'), 'f')

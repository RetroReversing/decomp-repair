from decomprepair.flag_positive_and import variants

SOURCE = '''void f(Obj *obj)
{
    s32 found = 0;
    s32 i;

    for (i = 0; i < 7; i++) {
        if (D_X[i] != 0xFFFF) {
            found = 1;
        }
    }
    if (found & ((obj->count & 0x3F) == 0)) {
        g();
    }
}
'''


def test_flag_is_written_positive():
    out = [s for _, s in variants(SOURCE, 'f')]
    assert out == [SOURCE.replace('if (found & ((', 'if (found > 0 & ((')]


def test_a_flag_with_other_values_is_left_alone():
    assert variants(SOURCE.replace('found = 1;', 'found = i;'), 'f') == []


def test_logical_and_and_masks_are_left_alone():
    assert variants(SOURCE.replace('found & ((', 'found && (('), 'f') == []
    assert variants(SOURCE.replace('(obj->count & 0x3F) == 0', 'obj->count & 0x3F'), 'f') == []

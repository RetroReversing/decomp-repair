from decomprepair.argument_weight_scope import FAMILY, variants

SOURCE = """void f(s32 arg0, void *arg1, s32 arg2) {
    u8 *table;
    s32 sp10, mag;
    if (arg0 != -1) {
        locate(arg1, arg2, &sp10);
        mag = angle(sp10, *(f32 *)((s8 *)arg1 + 0x38));
        do { table = gOption; } while (0);
        if (table[0] != 0) {
            use(arg0, mag);
            if (table[0] >= 2U) {
                use2(arg0, mag);
            }
        }
    }
}
"""


def _found(source=SOURCE, name='f'):
    return [text for family, text in variants(source, name) if family == FAMILY]


def test_the_first_call_naming_a_parameter_is_wrapped_with_the_pointer_written_out():
    found = _found()
    both = [text for text in found if 'do { table = gOption; }' not in text and 'table' not in text]
    assert both, found
    out = both[0]
    assert 'do { locate(arg1, arg2, &sp10); } while (0);' in out
    assert 'gOption[0] != 0' in out and 'gOption[0] >= 2U' in out
    assert 'u8 *table' not in out


def test_the_wrapper_alone_keeps_the_pointer():
    alone = [text for text in _found() if 'u8 *table;' in text and 'do { locate(' in text]
    assert alone


def test_nothing_without_a_call_that_names_a_used_parameter():
    assert not _found('void f(s32 a) {\n  g(1);\n}\n')


def test_a_pointer_read_other_than_through_an_index_is_left_in_place():
    source = SOURCE.replace('table[0] >= 2U', '*table >= 2U')
    assert all('u8 *table;' in text for text in _found(source))


LIST_WALK = """void walk(s32 arg0) {
    void *obj;
    void *kid;
    for (obj = gHead; obj != NULL; obj = *(void **)((s8 *)obj + 0x1C)) {
        for (kid = *(void **)((s8 *)obj + 8); kid != NULL; kid = *(void **)((s8 *)kid + 8)) {
            prepare(obj, arg0);
            color(arg0, *(u8 *)((s8 *)kid + 0x45), 0);
            submit(kid, arg0);
        }
        for (kid = *(void **)obj; kid != NULL; kid = *(void **)kid) {
            color(arg0, 1, 0);
            submit_child(kid, obj, arg0);
        }
    }
}
"""


def test_the_last_calls_naming_the_parameter_are_wrapped_together_several_deep():
    found = _found(LIST_WALK, 'walk')
    three_deep_last_two = [text for text in found
                           if 'do { do { do { submit_child(kid, obj, arg0); } while (0); } while (0); } while (0);' in text
                           and 'do { do { do { color(arg0, 1, 0); } while (0); } while (0); } while (0);' in text
                           and 'color(arg0, 1, 0);' in text and 'prepare(obj, arg0);\n' in text]
    assert three_deep_last_two, found


def test_the_group_does_not_wrap_a_call_the_single_wrapper_already_wrapped():
    source = LIST_WALK.replace('submit(kid, arg0);', 'do { submit(kid, arg0); } while (0);')
    for text in _found(source, 'walk'):
        assert text.count('submit(kid, arg0)') == 1


def test_every_group_child_compiles_to_the_same_braces():
    for text in _found(LIST_WALK, 'walk'):
        assert text.count('{') == text.count('}')
        assert text.count('do {') == text.count('while (0);')

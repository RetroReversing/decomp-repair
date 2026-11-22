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


def _found(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


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

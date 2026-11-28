"""An unguarded counted `do` loop written as its `for`."""
from decomprepair.unguarded_do_for import FAMILY, variants

SOURCE = """void walk(void) {
    s32 temp;
    u32 i;

    i = 0;
    store(1);
    store(2);
    store(3);
    store(4);
    store(5);
    store(6);
    store(7);
    do {
        temp = rows[i].a;
        i += 1;
        if (temp != 0) {
            f(rows[i - 1].b, temp);
        }
    } while (i < 0xA3U);
}
"""


def test_the_set_moves_into_the_header_and_the_step_to_it():
    ((family, text),) = variants(SOURCE, 'walk')
    assert family == FAMILY
    assert 'for (i = 0; i < 0xA3U; i++) {' in text
    assert 'f(rows[i].b, temp);' in text
    assert 'i = 0;\n' not in text and 'i += 1;' not in text and 'while' not in text
    assert text.index('store(7);') < text.index('for (')


def test_a_counter_read_after_its_step_or_a_continue_is_declined():
    assert variants(SOURCE.replace('f(rows[i - 1].b, temp);', 'f(rows[i].b, temp);'), 'walk') == []
    assert variants(SOURCE.replace('        i += 1;\n', '        if (temp) continue;\n        i += 1;\n'), 'walk') == []

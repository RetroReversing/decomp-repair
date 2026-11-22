"""A search loop's not-found value written on the exit path only (a 219-instruction N64 function, KMC GCC 2.7.2)."""
from decomprepair import loop_exit_value_block as e

SOURCE = '''s32 find(u8 *data, u16 key)
{
    u8 *entry;
    u8 *found;
    entry = data + *(s32 *)data;
    found = 0;
    while (*(s32 *)entry != -1) {
        found = entry;
        if (*(u16 *)(entry + 4) == key) break;
        entry += *(s32 *)entry;
        found = 0;
    }
    if (found) {
        use(found + 8);
    }
    return 0;
}
'''


def _texts(source=SOURCE):
    found = e.variants(source, 'find')
    assert all(family == e.FAMILY for family, _ in found)
    return [text for _, text in found]


def test_the_value_is_set_on_each_exit():
    out = _texts()[0]
    assert ('while (*(s32 *)entry != -1) { if (*(u16 *)(entry + 4) == key) { found = entry; goto exit_value_1; }'
            in out)
    assert 'entry += *(s32 *)entry; } found = 0; exit_value_1:;' in out
    assert 'found = 0;\n    while' not in out


def test_two_loops_get_two_labels():
    two = SOURCE.replace('    return 0;', SOURCE.split('    found = 0;', 1)[1].split('    if (found)')[0].join(['    found = 0;', '']) + '    return 0;')
    out = _texts(two)[0]
    assert 'exit_value_1:;' in out and 'exit_value_2:;' in out


def test_a_value_read_in_the_loop_is_left_alone():
    assert _texts(SOURCE.replace('entry += *(s32 *)entry;', 'entry += found ? 1 : *(s32 *)entry;')) == []


def test_a_loop_without_the_clearing_init_is_left_alone():
    assert _texts(SOURCE.replace('    found = 0;\n    while', '    while')) == []

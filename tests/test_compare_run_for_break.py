"""m2c's `goto` compare of two runs written as the indexed `for` with a `break` (a directory search, 3190 -> 0)."""
from decomprepair.compare_run_for_break import FAMILY, SHARED, variants

SOURCE = """s32 find_name(Entry *entries, u8 *name, u8 *ext, s32 *out)
{
    u8 key[16];
    u8 tag[4];
    s32 var_a0;
    s32 var_a0_2;
    s32 var_a3;
    u8 *var_a1;
    u8 *var_a1_2;
    u8 *var_a2;
    u8 *var_a2_2;

    load(entries, key, tag);
    var_a3 = 0;
    var_a0 = 0;
    var_a2 = name;
    var_a1 = key;
loop_9:
    var_a2 += 1;
    if (*var_a1 == *var_a2) {
        var_a0 += 1;
        var_a1 += 1;
        if (var_a0 < 0x10) {
            goto loop_9;
        }
    } else {
        var_a3 = 1;
    }
    if (var_a3 == 0) {
        do { var_a0_2 = 0;
        var_a2_2 = ext; } while (0);
        var_a1_2 = tag;
loop_13:
        if (*var_a1_2 != *var_a2_2) {
            var_a3 = 1;
        } else {
            var_a0_2 += 1;
            var_a1_2 += 1;
            var_a2_2 += 1;
            if (var_a0_2 < 4) goto loop_13;
        }
    }
    *out = var_a3;
    return 0;
}
"""


def children(source=SOURCE):
    return variants(source, 'find_name')


def test_every_compare_becomes_an_indexed_for_with_one_shared_counter():
    family, text = children()[0]
    assert family == SHARED
    assert 'goto' not in text and 'loop_9' not in text and 'do {' not in text
    assert ('    for (var_a0 = 0; var_a0 < 0x10; var_a0++) {\n        if (key[var_a0] != name[var_a0]) {\n'
            '            var_a3 = 1;\n            break;\n        }\n    }\n') in text
    assert 'for (var_a0 = 0; var_a0 < 4; var_a0++) {' in text
    assert 'if (tag[var_a0] != ext[var_a0]) {' in text
    assert 's32 var_a0_2;' not in text


def test_each_compare_is_also_offered_with_its_own_counter():
    found = children()
    assert [family for family, _ in found] == [SHARED, FAMILY, FAMILY, FAMILY]
    assert 'for (var_a0_2 = 0; var_a0_2 < 4; var_a0_2++)' in found[1][1]
    assert 'goto loop_13' in found[2][1] and 'goto loop_9' not in found[2][1]


def test_a_compare_already_indexed_keeps_its_subscripts():
    source = """void f(u8 *a, u8 *b, s32 *fail)
{
    s32 i;

    i = 0;
loop_a:
    if (a[i] == b[i]) {
        i++;
        if (i < 16) goto loop_a;
    } else {
        *fail = 1;
    }
}
"""
    [(family, text)] = variants(source, 'f')
    assert family == FAMILY
    assert 'for (i = 0; i < 16; i++) {\n        if (a[i] != b[i]) {\n            *fail = 1;\n            break;' in text


def test_a_pointer_of_another_type_is_indexed_through_a_cast():
    source = SOURCE.replace('u8 key[16];', 's8 key[16];')
    assert 'if (((u8 *) key)[var_a0] != name[var_a0]) {' in children(source)[0][1]


def test_a_pointer_read_after_the_loop_declines():
    source = SOURCE.replace('*out = var_a3;', '*out = *var_a1 + *var_a1_2;')
    assert children(source) == []


def test_a_counter_used_afterwards_is_not_shared():
    found = children(SOURCE.replace('*out = var_a3;', '*out = var_a0_2;'))
    assert [family for family, _ in found] == [FAMILY, FAMILY, FAMILY]

"""loop_guard_pointer_sink: a pointer to a global set before a `for` loop that reads through it, set in its guard.

Synthetic shape of the 108-instruction SN64 GCC 2.8.1 cheat-code checker (220 -> 0)."""
from decomprepair import loop_guard_pointer_sink as s

SOURCE = '''void check(Input *in) {
    Cheat *c;
    s32 found;
    s32 *key;

    key = &D_801070A0;
    if (D_801070A0 != 0) {
        found = 0;
        for (c = D_800AA388; c->codes != NULL; c++) {
            if (c->active != 0) {
                if (*key != c->codes[in->pos]) {
                    c->active = 0;
                } else {
                    found = 1;
                }
            }
        }
        if (found) {
            in->pos++;
        }
    }
}
'''


def test_the_set_moves_into_the_guard_of_a_do_loop():
    found = s.variants(SOURCE, 'check')
    assert [family for family, _ in found] == [s.FAMILY, s.FAMILY]
    as_do, as_for = (text for _, text in found)
    assert '    key = &D_801070A0;\n    if (D_801070A0' not in as_do
    assert ('        c = D_800AA388;\n        if (c->codes != NULL) {\n            key = &D_801070A0;\n            do {\n'
            '                if (c->active != 0) {\n') in as_do
    assert '                c++;\n            } while (c->codes != NULL);\n        }\n        if (found) {' in as_do
    assert '            key = &D_801070A0;\n            for (; c->codes != NULL; c++) {\n' in as_for
    assert '                    if (*key != c->codes[in->pos]) {' in as_do


def test_declines_when_the_pointer_is_read_elsewhere_or_the_body_continues():
    assert s.variants(SOURCE.replace('            in->pos++;', '            in->pos += *key;'), 'check') == []
    assert s.variants(SOURCE.replace('    if (D_801070A0 != 0) {', '    if (*key != 0) {'), 'check') == []
    assert s.variants(SOURCE.replace('                    found = 1;', '                    found = 1;\n                    continue;'),
                      'check') == []
    assert s.variants(SOURCE.replace('c->codes != NULL; c++', 'next(c) != NULL; c++'), 'check') == []

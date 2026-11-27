from decomprepair.found_value_return import FAMILY, variants

SAVED = '''s32 *f(s32 *list, s32 key) {
    s32 *var_v0;

    var_v0 = NULL;
    while (*list != 0) {
        if (*list == key) {
            var_v0 = list;
            if (key == 1) {
                return var_v0;
            }
            return var_v0;
        }
        list++;
    }
    return var_v0;
}
'''


def test_the_result_variable_becomes_the_returns():
    [(family, text)] = variants(SAVED, 'f')
    assert family == FAMILY
    assert 'var_v0' not in text
    assert text.count('return list;') == 2 and text.count('return NULL;') == 1


def test_left_alone_when_the_value_can_outlive_its_block_or_change():
    assert variants(SAVED.replace('            return var_v0;\n        }\n        list++;',
                                  '        }\n        list++;'), 'f') == []
    assert variants(SAVED.replace('if (key == 1) {', 'list += 1;\n            if (key == 1) {'), 'f') == []
    assert variants(SAVED.replace('var_v0 = NULL;', 'var_v0 = list + 1;'), 'f') == []

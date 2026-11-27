from decomprepair import return_carrier_merge as merge

SOURCE = '''s32 f(void) {
    s32 temp;
    s32 var_a0;
    s32 var_v0;

    temp = probe();
    if (temp == 0) {
        flag = 1;
        var_a0 = 3;
        goto block_9;
    }
    if (temp == 0xB) {
        var_a0 = other();
        if (var_a0 != 0) {
            goto block_8;
        }
        goto block_9;
    }
    if ((temp == 4) || (var_v0 = temp, (temp == 0xA))) {
block_8:
        var_a0 = 2;
block_9:
        var_v0 = var_a0;
    }
    return var_v0;
}
'''


def children(source):
    return merge.variants(source, 'f')


def test_ladder_carriers_become_one_variable():
    found = children(SOURCE)
    assert found and {family for family, _ in found} == {merge.FAMILY}
    text = found[0][1]
    assert 'var_v0' not in text and 'var_a0' not in text
    assert 'temp = probe();' in text and 'temp = other();' in text
    assert 'if ((temp == 4) || (temp == 0xA)) {' in text
    assert 'block_9:\n        ;\n' in text
    assert 'return temp;' in text


def test_returned_name_can_survive():
    assert any('return var_v0;' in text and 'var_v0 = probe();' in text for _, text in children(SOURCE))


def test_a_value_still_read_later_is_not_merged():
    source = SOURCE.replace('var_a0 = other();\n        if (var_a0 != 0)', 'var_a0 = other();\n        if (temp != var_a0)')
    assert children(source) == []


def test_an_updated_member_or_other_type_is_not_merged():
    assert children(SOURCE.replace('var_a0 = 2;', 'var_a0 += 2;')) == []
    assert children(SOURCE.replace('s32 var_a0;', 'u8 var_a0;')) == []


def test_a_comma_copy_needs_the_body_to_copy_again():
    assert children(SOURCE.replace('        var_v0 = var_a0;\n    }', '    }')) == []

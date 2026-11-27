from decomprepair.division_in_place import FAMILY, variants

SOURCE = '''s32 g(s32 *, s32);
void f(s32 arg0, s32 *arg1) {
    s32 temp_s1;
    s32 var_s1;
    var_s1 = 0x1000;
    if (arg1[arg0] != 0) {
        var_s1 = arg1[arg0 + 2];
    }
    var_s1 = var_s1 * 0x10CC;
    if (var_s1 < 0) {
        var_s1 += 0xFFF;
    }
    temp_s1 = var_s1 >> 0xC;
    arg1[7] = temp_s1;
    g(arg1, 0x01000000 / temp_s1);
    arg1[8] = temp_s1;
}
'''


def children(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_quotient_goes_back_into_the_dividend_with_the_product():
    in_place = children()[0]
    assert 'var_s1 = (var_s1 * 0x10CC) / 0x1000;' in in_place
    assert 'temp_s1' not in in_place
    assert 'g(arg1, 0x01000000 / var_s1);' in in_place
    assert 'arg1[8] = var_s1;' in in_place
    assert '+= 0xFFF' not in in_place


def test_the_quotient_in_its_own_local_is_the_second_child():
    own = children()[1]
    assert 'temp_s1 = (var_s1 * 0x10CC) / 0x1000;' in own
    assert 's32 temp_s1;' in own
    assert '+= 0xFFF' not in own


def test_braceless_bias_and_a_cast_shift():
    source = SOURCE.replace('''    if (var_s1 < 0) {
        var_s1 += 0xFFF;
    }
    temp_s1 = var_s1 >> 0xC;''', '''    if (var_s1 < 0) var_s1 += 0xFFF;
    temp_s1 = (s32) var_s1 >> 12;''')
    assert 'var_s1 = (var_s1 * 0x10CC) / 0x1000;' in children(source)[0]


def test_a_dividend_read_later_keeps_its_own_value():
    source = SOURCE.replace('    arg1[8] = temp_s1;', '    arg1[8] = var_s1;')
    texts = children(source)
    assert len(texts) == 1
    assert 'temp_s1 = (var_s1 * 0x10CC) / 0x1000;' in texts[0]


def test_nothing_when_the_bias_is_not_the_shift_s():
    assert children(SOURCE.replace('0xFFF', '0x7FF')) == []


def test_nothing_when_the_quotient_name_was_used_before():
    source = SOURCE.replace('    var_s1 = 0x1000;\n', '    var_s1 = 0x1000;\n    temp_s1 = 3;\n    arg1[1] = temp_s1;\n')
    assert children(source) == []


def test_unsigned_locals_are_left_alone():
    assert children(SOURCE.replace('    s32 var_s1;', '    u32 var_s1;')) == []

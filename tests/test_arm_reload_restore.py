from decomprepair.arm_reload_restore import FAMILY, variants

SOURCE = '''
inline static int reload(u8 *table, u8 index)
{
    return table[index] & 0xFF;
}

void f(u8 *table, u8 *code, u8 *out, s32 kind)
{
    s32 a;
    s32 b;
    s32 c;
    u32 tmp;
    switch (kind) {
    case 3:
        tmp = table[code[1]];
        out[0] = tmp;
        c = table[code[2]];
        out[1] = (u8) c;
        tmp = table[code[3]];
        a = reload(table, code[1]);
        a = (u8) tmp;
        b = c & 0xFF;
        c = tmp & 0xFF;
        out[2] = tmp;
        out += 3;
        break;
    default:
        a = 0;
        break;
    }
    use(a, b, c);
}
'''


def restored(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_dead_reload_gets_the_first_value_and_each_value_a_local():
    text, = restored()
    assert 'case 3: {' in text
    assert 'u8 first;' in text and 'u8 second;' in text
    assert 'first = table[code[1]];\n        out[0] = first;' in text
    assert 'second = table[code[2]];\n        out[1] = (u8) second;' in text
    assert 'a = first & 0xFF;' in text and 'b = second & 0xFF;' in text
    assert 'a = (u8) tmp;' not in text and 'reload(table, code[1])' not in text
    # the third value keeps the scratch local: it leaves the arm
    assert 'tmp = table[code[3]];' in text and 'c = tmp & 0xFF;' in text and 'out[2] = tmp;' in text
    assert 'out += 3;\n        }\n        break;' in text
    assert 'case 3: {\n        u8 first; u8 second;\n        first = table' in text


def test_an_arm_without_the_dead_pair_stays():
    assert not restored(SOURCE.replace('        a = (u8) tmp;\n', '        b = 1;\n'))


def test_a_reload_of_another_element_stays():
    assert not restored(SOURCE.replace('reload(table, code[1])', 'reload(table, code[4])'))


def test_an_arm_with_control_flow_stays():
    assert not restored(SOURCE.replace('        out += 3;\n', '        if (kind) { out += 3; }\n'))


def test_a_word_table_stays():
    assert not restored(SOURCE.replace('u8 *table', 'u32 *table'))


def test_a_taken_name_gets_a_suffix():
    text, = restored(SOURCE.replace('s32 a;', 's32 a; s32 first = 0;'))
    assert 'first_1' in text

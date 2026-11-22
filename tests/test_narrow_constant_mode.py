from decomprepair import narrow_widening_repairs as repair

SOURCE = '''
void f(char *record) {
    u8 earlier_a;
    u8 earlier_b;
    u8 earlier_c;
    u8 earlier_d;
    u8 earlier_e;
    u8 earlier_f;
    u8 earlier_g;
    u8 earlier_h;
    u8 mode;
    mode = 1;
    if (poll()) {
        mode = 2;
    }
    if (mode != (*((u8 *) (record + 3)))) {
        *((u8 *) (record + 3)) = mode;
    }
}
'''


def mode_choices(source):
    return [text for family, text in repair.variants(source, 'f')
            if family == repair.CONSTANT_MODE_FAMILY]


def test_constant_mode_reaches_the_front_of_the_width_proposals():
    first, *_ = repair.variants(SOURCE, 'f')
    assert first == (repair.CONSTANT_MODE_FAMILY, SOURCE.replace('u8 mode;', 's32 mode;'))


def test_skips_nonconstant_writes_and_escaped_modes():
    for text in ('mode += 1;', 'mode = 300;', 'mode = read_mode();',
                 'record_mode(&(mode));', '++mode;', 'record_mode(sizeof(mode));'):
        assert not mode_choices(SOURCE.replace('        mode = 2;', '        mode = 2;\n        ' + text))


def test_requires_a_byte_field_comparison():
    assert not mode_choices(SOURCE.replace('mode != (*((u8 *)', 'mode != (*((f32 *)'))

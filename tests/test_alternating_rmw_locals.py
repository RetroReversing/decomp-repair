from decomprepair import alternating_rmw_locals as family

SOURCE = '''void f(void *p) {
    M2C_FIELD(p, s32 *, 0x34) = (s32) (M2C_FIELD(p, s32 *, 0x34) + 1);
    M2C_FIELD(p, u16 *, 0xC) += 0x7A;
    M2C_FIELD(p, s32 *, 0x3C) += 0x4A2E;
    M2C_FIELD(p, u8 *, 0x72) = (u8) (M2C_FIELD(p, u8 *, 0x72) - 6);
    M2C_FIELD(p, u8 *, 0x71) = (u8) (M2C_FIELD(p, u8 *, 0x71) - 6);
    M2C_FIELD(p, u8 *, 0x73) = (u8) (M2C_FIELD(p, u8 *, 0x73) - 6);
    if ((u8) M2C_FIELD(p, u8 *, 0x71) < 8U) {
        g(p);
    }
}
'''


def test_updates_take_turns_and_the_compare_is_staged_with_the_last_update():
    turns, held, tail = [child for _, child in family.variants(SOURCE, 'f')]
    assert 's32 rmw_first;\n    u32 rmw_second;' in turns
    assert 'rmw_second = M2C_FIELD(p, u16 *, 0xC); rmw_second += 0x7A; M2C_FIELD(p, u16 *, 0xC) = rmw_second;' in turns
    assert 'rmw_second = M2C_FIELD(p, u8 *, 0x73); rmw_second -= 6;' in turns
    assert 'rmw_first = M2C_FIELD(p, u8 *, 0x73); rmw_first -= 6;' in held
    assert ('rmw_first = M2C_FIELD(p, u8 *, 0x73); rmw_second = M2C_FIELD(p, u8 *, 0x71); '
            'M2C_FIELD(p, u8 *, 0x73) = rmw_first - 6;\n    do { rmw_second = rmw_second < 8U; } while (0);') in tail
    assert 'if (rmw_second) {' in tail


def test_fields_without_a_visible_integer_type_are_left_alone():
    floats = 'void f(T *p) {\n    p->a += 1;\n    p->b += 1;\n    p->c += 1;\n}\n'
    assert family.variants(floats, 'f') == []
    assert family.variants(SOURCE.replace('s32 *', 'f32 *').replace('u16 *', 'f32 *'), 'f') != []
    short = 'void f(void *p) {\n    M2C_FIELD(p, f32 *, 0) += 1;\n    M2C_FIELD(p, f32 *, 4) += 1;\n    M2C_FIELD(p, s32 **, 8) += 1;\n}\n'
    assert family.variants(short, 'f') == []


def test_a_signed_field_keeps_the_compare_as_it_was():
    signed = SOURCE.replace('u8 *, 0x71', 's8 *, 0x71')
    assert len(family.variants(signed, 'f')) == 2

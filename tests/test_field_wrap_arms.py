from decomprepair import registry
from decomprepair.field_wrap_arms import FAMILY, variants

DRAFT = """
void wrap(void *arg0) {
    s16 temp_a1;
    s16 var_v0;
    u16 temp_v1;
    s32 temp_a2;
    u16 temp_v2;

    if (gMode != 0) {
        temp_a1 = M2C_FIELD(arg0, s16 *, 0);
        temp_v1 = (u16) M2C_FIELD(arg0, s16 *, 0);
        var_v0 = temp_v1 + 0x100;
        if ((temp_a1 < -0x80) || (var_v0 = temp_v1 - 0x100, ((temp_a1 < 0x81) == 0))) {
            M2C_FIELD(arg0, s16 *, 0) = var_v0;
        }
        temp_a1 = M2C_FIELD(arg0, s16 *, 2);
        temp_v1 = (u16) M2C_FIELD(arg0, s16 *, 2);
        if (temp_a1 < -0x40) {
            M2C_FIELD(arg0, s16 *, 2) = (s16) (temp_v1 + 0x70);
            return;
        }
        if (temp_a1 >= 0x41) {
            M2C_FIELD(arg0, s16 *, 2) = (s16) (temp_v1 - 0x70);
        }
    } else {
        do { temp_a2 = M2C_FIELD(arg0, s16 *, 2); } while (0);
        temp_v2 = (u16) M2C_FIELD(arg0, s16 *, 2);
        var_v0 = temp_v2 + 0x600;
        if ((temp_a2 < -0x300) || (var_v0 = temp_v2 - 0x600, ((temp_a2 < 0x301) == 0))) {
            M2C_FIELD(arg0, s16 *, 2) = var_v0;
        }
        do { M2C_FIELD(arg0, s16 *, 0) = (s16) ((u16) M2C_FIELD(arg0, s16 *, 0) - 0x8000); } while (0);
    }
}
"""


def flat(text):
    return ' '.join(text.split())


def test_every_site_together_comes_first():
    children = variants(DRAFT, 'wrap')
    assert [family for family, _ in children] == [FAMILY] * 5
    combined = flat(children[0][1])
    x, y = 'M2C_FIELD(arg0, s16 *, 0)', 'M2C_FIELD(arg0, s16 *, 2)'
    assert f'if ({x} < -0x80) {{ {x} += 0x100; }} else if (!({x} < 0x81)) {{ {x} -= 0x100; }}' in combined
    assert f'if ({y} < -0x40) {{ {y} += 0x70; }} else if ({y} >= 0x41) {{ {y} -= 0x70; }}' in combined
    assert f'if ({y} < -0x300) {{ {y} += 0x600; }} else if (!({y} < 0x301)) {{ {y} -= 0x600; }}' in combined
    assert f'do {{ {x} -= 0x8000; }} while (0);' in combined
    assert 'return;' not in combined and 'var_v0 =' not in combined and 'temp_v1 =' not in combined
    assert variants(children[0][1], 'wrap') == []


def test_an_unsigned_field_is_compared_signed():
    source = DRAFT.replace('s16 *, 0', 'u16 *, 0')
    combined = flat(variants(source, 'wrap')[0][1])
    assert 'if ((s16) M2C_FIELD(arg0, u16 *, 0) < -0x80)' in combined


def test_a_temporary_read_later_keeps_its_site():
    source = DRAFT.replace('        temp_a1 = M2C_FIELD(arg0, s16 *, 2);\n', '        use(var_v0);\n'
                           '        temp_a1 = M2C_FIELD(arg0, s16 *, 2);\n')
    assert 'var_v0 = temp_v1 + 0x100;' in variants(source, 'wrap')[0][1]


def test_a_guard_with_code_after_it_keeps_its_return():
    source = DRAFT.rstrip()[:-1] + '    use(arg0);\n}\n'
    assert 'return;' in variants(source, 'wrap')[0][1]


def test_a_returning_function_and_a_wider_copy_are_left_alone():
    assert 'return;' in variants(DRAFT.replace('void wrap', 's32 wrap'), 'wrap')[0][1]
    narrow = DRAFT.replace('(u16) M2C_FIELD', '(u8) M2C_FIELD')
    assert variants(narrow, 'wrap') == []


def test_the_registry_runs_it():
    assert registry.get('field_wrap_arms').families == (FAMILY,)


SAVED = """
void wrap(void *arg0) {
    s16 temp_a1;
    s16 temp_a1_2;
    s16 var_v0;
    u16 temp_v1;
    u16 temp_v1_2;

    temp_a1 = (*(s16 *)((char *)(arg0) + 2));
    var_v0 = temp_v1 + 0x100;
    temp_v1 = (u16) (*(s16 *)((char *)(arg0) + 2));
    if ((temp_a1 < -0x80) || (var_v0 = temp_v1 - 0x100, ((temp_a1 < 0x81) == 0))) {
        (*(s16 *)((char *)(arg0) + 2)) = var_v0;
    }
    temp_a1 = (*(s16 *)((char *)(arg0) + 0));
    temp_v1_2 = (u16) (*(s16 *)((char *)(arg0) + 0));
    if (temp_a1 < -0x40) {
        var_v0 = (s16) ((s32)temp_v1_2 + 0x70);
        (*(s16 *)((char *)(arg0) + 0)) = var_v0;
        return;
    }
    if (temp_a1 >= 0x41) {
        (*(s16 *)((char *)(arg0) + 0)) = (s16) (temp_v1_2 - 0x70);
    }
}
"""


def test_a_saved_bests_spelling_is_read():
    children = variants(SAVED, 'wrap')
    combined = flat(children[0][1])
    x, y = '(*(s16 *)((char *)(arg0) + 0))', '(*(s16 *)((char *)(arg0) + 2))'
    assert f'if ({y} < -0x80) {{ {y} += 0x100; }} else if (!({y} < 0x81)) {{ {y} -= 0x100; }}' in combined
    assert f'if ({x} < -0x40) {{ {x} += 0x70; }} else if ({x} >= 0x41) {{ {x} -= 0x70; }}' in combined
    assert 'var_v0 =' not in combined and 'temp_a1 =' not in combined and 'return;' not in combined


def test_a_copy_already_set_keeps_the_early_sum():
    source = SAVED.replace('    temp_a1 = (*(s16 *)((char *)(arg0) + 2));\n', '    temp_v1 = 3;\n'
                           '    temp_a1 = (*(s16 *)((char *)(arg0) + 2));\n', 1)
    assert 'var_v0 = temp_v1 + 0x100;' in variants(source, 'wrap')[0][1]

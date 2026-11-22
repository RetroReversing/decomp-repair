from decomprepair.switch_variable_split_repairs import FAMILY, variants

SOURCE = '''void f(void *p)
{
    s32 value;
    void *ptr;
    void *other;
    value = *(s16 *)((char *)p + 0x7A);
    other = p;
    switch (value)
    {
        case 3:
            ptr = *(void **)((char *)p + 0xA8);
            value = 4;
            goto done;
        case 8:
            ptr = *(void **)((char *)p + 0xA8);
            value = 2;
            goto done;
        default:
            break;
        done:
            *(s16 *)((char *)ptr + 0x7A) = value;
    }
}
'''


def test_selector_gets_its_own_name_inside_the_switch():
    [(family, fixed)] = [v for v in variants(SOURCE, 'f') if 'value_arm' in v[1]]
    assert family == FAMILY
    assert 's32 value_arm;' in fixed
    assert 'switch (value)' in fixed
    assert 'value_arm = 4;' in fixed and '= value_arm;' in fixed
    assert 'value = *(s16' in fixed


def test_variable_read_after_the_switch_or_inside_before_assignment_is_kept():
    assert variants(SOURCE.replace('    }\n}', '    }\n    use(value);\n}'), 'f') == []
    reads_first = SOURCE.replace('ptr = *(void **)((char *)p + 0xA8);\n            value = 4;',
                                 'use(value);\n            value = 4;', 1)
    assert not [v for v in variants(reads_first, 'f') if 'value_arm' in v[1]]

from decomprepair.guard_zero_return_label import FAMILY, LABEL, variants

SOURCE = '''
s32 f(void **list, f32 *out)
{
    void *found;
    found = NULL;
    if (list != NULL)
    {
        do
        {
            if (hit(list))
            {
                return 1;
            }
            found = pick(list);
            list = *list;
        }
        while (list != NULL);
    }
    check:
    if (found == NULL)
    {
        return 0;
    }
    copy(out, found);
    return 1;
}
'''


def texts(source):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_the_guard_jumps_to_the_labelled_zero_return():
    (text,) = texts(SOURCE)
    assert f'if (list == NULL)\n    {{\n      goto {LABEL};\n    }}\n    {{' in text
    assert f'{LABEL}:\n        return 0;' in text
    assert text.count('return 0;') == 1


def test_a_bare_pointer_guard_is_turned_too():
    (text,) = texts(SOURCE.replace('if (list != NULL)', 'if (list)'))
    assert 'if (!list)' in text


def test_a_guard_with_an_else_or_other_code_before_the_zero_test_stays():
    assert not texts(SOURCE.replace('    check:\n', '    else\n    {\n        found = 0;\n    }\n'))
    assert not texts(SOURCE.replace('    check:\n', '    copy(out, 0);\n'))


def test_a_nested_guard_stays():
    nested = SOURCE.replace('    if (list != NULL)\n', '    if (out)\n    if (list != NULL)\n')
    assert all('if (list == NULL)' not in text for text in texts(nested))

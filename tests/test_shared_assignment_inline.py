from decomprepair.shared_assignment_inline import FAMILY, variants

SOURCE = '''void f(void)
{
    s32 base;
    s32 kind;
    s32 var_a0;
    base = get(0x162);
    kind = peek();
    if (kind >= 0)
    {
        if (kind)
        {
            var_a0 = base - 0x28;
        }
        else
        {
            var_a0 = base - 0x28;
        }
        if (kind >= 2)
        {
            var_a0 = base - 0x28;
            goto draw;
        }
        erase(var_a0, base, 1);
    }
    else
    {
        draw:
        paint(var_a0, base, 2);
    }
}
'''


def moved(source=SOURCE):
    return [text for family, text in variants(source, 'f') if family == FAMILY]


def test_every_read_gets_the_expression_and_the_assignments_go():
    texts = moved()
    assert len(texts) == 2
    clean = texts[0]
    assert 'erase(base - 0x28, base, 1);' in clean and 'paint(base - 0x28, base, 2);' in clean
    assert 'var_a0' not in clean
    assert 'if (kind)' not in clean and 'goto draw;' in clean
    assert 'if (kind)' in texts[1] and 'var_a0' not in texts[1]


def test_an_expression_name_assigned_twice_stays():
    assert not moved(SOURCE.replace('    if (kind >= 0)\n', '    base = 1;\n    if (kind >= 0)\n'))


def test_different_expressions_stay():
    assert not moved(SOURCE.replace('goto draw;', 'goto draw;').replace('var_a0 = base - 0x28;\n            goto', 'var_a0 = base - 0x30;\n            goto'))


def test_a_local_stepped_or_addressed_stays():
    assert not moved(SOURCE.replace('erase(var_a0, base, 1);', 'var_a0 += 1;\n        erase(var_a0, base, 1);'))
    assert not moved(SOURCE.replace('erase(var_a0, base, 1);', 'erase(&var_a0, base, 1);'))


def test_a_global_in_the_expression_stays():
    assert not moved(SOURCE.replace('base - 0x28', 'gBase - 0x28'))


def test_one_assignment_is_not_this_family():
    one = SOURCE.replace('''        if (kind)
        {
            var_a0 = base - 0x28;
        }
        else
        {
            var_a0 = base - 0x28;
        }
''', '').replace('''            var_a0 = base - 0x28;
            goto draw;''', '''            goto draw;''')
    assert not moved(one)


def test_names_ending_in_digits_are_names():
    texts = moved(SOURCE.replace('base', 'temp_s6'))
    assert texts and 'erase(temp_s6 - 0x28, temp_s6, 1);' in texts[0]

from decomprepair.switch_value_copy import variants

SOURCE = '''void f(void *p) {
    u8 x;
    u8 y;
    x = read(p);
    y = read(p);
    switch (y) {
    case 1:
        use(x, x);
        break;
    case 2:
        other(x);
        break;
    }
}
'''


def test_copy_one_arm():
    children = [text for _, text in variants(SOURCE, 'f')]
    assert len(children) == 1
    assert 'x_copy = x;' in children[0]
    assert 'use(x_copy, x_copy)' in children[0]
    assert 'other(x)' in children[0]


def test_mutation_or_address_taken_not_copied():
    for text in (SOURCE.replace('use(x, x);', 'x++; use(x, x);'),
                 SOURCE.replace('other(x);', 'other(&x);'),
                 SOURCE.replace('use(x, x);', 'x = 1; use(x, x);')):
        assert not variants(text, 'f')


def test_later_arm_can_change_the_value():
    assert variants(SOURCE.replace('other(x);', 'x++; other(x);'), 'f')


def test_loop_and_goto_are_not_rewritten():
    assert not variants(SOURCE.replace('switch (y)', 'while (y) switch (y)'), 'f')
    assert not variants(SOURCE.replace('switch (y)', 'goto again; again: switch (y)'), 'f')


def test_conditional_initialization_is_not_copied():
    assert not variants(SOURCE.replace('    x = read(p);', '    if (y)\n        x = read(p);'), 'f')

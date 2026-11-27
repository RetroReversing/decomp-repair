from decomprepair.switch_if_chain import variants

SOURCE = '''void f(void)
{
    switch (mode) {
    case 0:
        draw(1);
        break;
    case 1: {
        draw(2);
        break;
    }
    }
    draw(3);
}
'''


def _flat(text):
    return ' '.join(text.split())


def test_a_two_case_switch_becomes_a_chain_that_reads_again():
    children = [_flat(text) for _, text in variants(SOURCE, 'f')]
    assert children == ['void f(void) { if (mode == 0) { draw(1); } else if (mode == 1) { draw(2); } draw(3); }']


def test_a_last_default_becomes_the_else():
    source = SOURCE.replace('    }\n    draw(3);', '    default:\n        draw(4);\n    }\n    draw(3);')
    assert 'else { draw(4); }' in _flat(variants(source, 'f')[0][1])


def test_fallthrough_inner_breaks_and_calls_are_left_alone():
    assert not variants(SOURCE.replace('        draw(1);\n        break;\n', '        draw(1);\n'), 'f')
    assert not variants(SOURCE.replace('draw(1);', 'if (x) break; draw(1);'), 'f')
    assert not variants(SOURCE.replace('switch (mode)', 'switch (next())'), 'f')

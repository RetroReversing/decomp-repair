from decomprepair.switch_copy_retarget import variants

SOURCE = '''void f(int input, int kind) {
    u8 x;
    u8 y;
    x = input;
    y = x;
    switch (kind) {
    case 1:
        use(y, y);
        break;
    case 2:
        use(x);
        break;
    case 3:
        use(x);
        break;
    }
}
'''


def test_retargets_copy_to_later_case():
    children = [text for _, text in variants(SOURCE, 'f')]
    assert any('use(x, x);' in text and 'case 2:\n        use(y);' in text for text in children)


def test_rejects_fallthrough_and_mutation():
    no_break = SOURCE.replace('        break;\n    case 2:', '        if (kind) break;\n    case 2:')
    assert not any('case 2:\n        use(y);' in text for _, text in variants(no_break, 'f'))
    assert not variants(SOURCE.replace('use(y, y);', 'x++; use(y, y);'), 'f')
    assert not variants(SOURCE.replace('use(y, y);', 'use(&y);'), 'f')
    assert not variants(SOURCE, 'f', '#define y other')

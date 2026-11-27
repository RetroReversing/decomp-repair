from decomprepair.labeled_store_scope import variants

SOURCE = '''void f(int i) {
    if (i) goto found;
    return;
found:
    output[i] = 2;
    finish();
}
'''


def test_label_stays_outside_the_scopes():
    children = variants(SOURCE, 'f')
    assert [text.count('do {') for _, text in children] == [1, 2, 4]
    assert all('found:\n    do {' in text and 'output[i] = 2;' in text for _, text in children)


def test_no_expanding_macros_or_line_sensitive_builtins():
    assert not variants(SOURCE, 'f', '#define output other')
    assert not variants(SOURCE, 'f', '#define i other')
    assert not variants(SOURCE + ' /* __LINE__ */', 'f')
    assert not variants(SOURCE.replace('output[i] = 2;', 'output[i++] = 2;'), 'f')
    assert not variants(SOURCE.replace('found:', 'case 1:'), 'f')

from decomprepair.single_local_copy_inline import variants

SOURCE = '''void f(int n) {
    s32 i;
    s32 copy;
    s32 j;
    for (i = 0; i < n; i++) {
        copy = i;
        for (j = 0; j < 4; j++) {
            if (copy == j) work();
        }
    }
}
'''


def test_inline_copy_into_nested_comparison():
    children = variants(SOURCE, 'f')
    assert len(children) == 1
    text = children[0][1]
    assert 'copy' not in text
    assert 'if (i == j)' in text


def test_rejects_mutation_escape_label_and_macros():
    assert not variants(SOURCE.replace('copy = i;', 'copy = i; i++;'), 'f')
    assert not variants(SOURCE.replace('copy = i;', 'save(&i); copy = i;'), 'f')
    assert not variants(SOURCE.replace('copy = i;', 'copy = i; next:'), 'f')
    assert not variants(SOURCE, 'f', '#define TOUCH() (i++)')
    assert not variants(SOURCE.replace('if (copy == j)', 'if (copy++ == j)'), 'f')
    assert not variants(SOURCE.replace('if (copy == j)', 'if (++copy == j)'), 'f')
    assert not variants(SOURCE.replace('copy = i;', 'if (n) copy = i;'), 'f')
    assert not variants(SOURCE.replace('copy = i;', 'if (n) { copy = i; }'), 'f')

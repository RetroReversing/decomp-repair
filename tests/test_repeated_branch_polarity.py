from decomprepair import branch_polarity_repairs

SOURCE = """void f(unsigned flags, int output) {
    if (!(flags & 4)) {
        keep_first();
    } else if (output) {
        set_first();
    }
    if (!(flags & 4)) {
        keep_second();
    } else {
        set_second();
    }
}"""


def test_flips_repeated_flag_tests_in_one_candidate():
    family, text = branch_polarity_repairs.variants(SOURCE, 'f')[0]
    assert family == 'branch_polarity'
    assert text.count('if (flags & 4)') == 2
    assert text.index('if (output)') < text.index('keep_first()')
    assert text.index('set_second()') < text.index('keep_second()')


def test_different_masks_are_not_grouped():
    source = SOURCE.replace('flags & 4', 'flags & 8', 1)
    for _, text in branch_polarity_repairs.variants(source, 'f'):
        assert '!(flags & 8)' in text or '!(flags & 4)' in text

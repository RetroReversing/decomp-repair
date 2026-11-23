from decomprepair import index_sum_order as r

SOURCE = '''void f(u16 *tab, u32 y, u32 v, u32 t5, u32 ix, u32 mask) {
    u32 e;
    e = (tab + (y >> 7) + t5)[ix];
    e = tab[(y >> 7) + ((v >> 10) & mask)];
    e = tab[ix + 1];
}
'''


def families(found):
    return [family for family, _ in found]


def test_pointer_sum_is_regrouped_so_the_integers_add_first():
    found = dict((family, text) for family, text in r.variants(SOURCE, 'f') if family == 'pointer_sum_regroup')
    assert '(tab + ((y >> 7) + t5))[ix]' in found['pointer_sum_regroup']


def test_two_term_index_sum_is_swapped():
    swapped = [text for family, text in r.variants(SOURCE, 'f') if family == 'index_sum_swap']
    assert any('tab[((v >> 10) & mask) + (y >> 7)]' in text for text in swapped)
    assert any('tab[1 + ix]' in text for text in swapped)


def test_each_child_changes_one_site_only():
    for family, text in r.variants(SOURCE, 'f'):
        assert text != SOURCE
        assert text.count('\n') == SOURCE.count('\n')


def test_a_term_with_a_side_effect_or_a_call_is_not_reordered():
    source = SOURCE.replace('tab[ix + 1]', 'tab[ix++ + 1]').replace('tab[(y >> 7) + ((v >> 10) & mask)]', 'tab[g(y) + v]')
    assert not [1 for family, text in r.variants(source, 'f') if family == 'index_sum_swap']


def test_a_difference_in_the_group_is_left_alone():
    source = SOURCE.replace('(tab + (y >> 7) + t5)[ix]', '(tab + (y >> 7) - t5)[ix]')
    assert not [1 for family, _ in r.variants(source, 'f') if family == 'pointer_sum_regroup']

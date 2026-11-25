"""A loop's `base + i + 1` staged as `t = base + 1; .. i + t` so loop.c hoists it (an N64 level loader, 1060 -> 625)."""
from decomprepair.loop_invariant_sum_stage import FAMILY, variants

SOURCE = """void load(s32 base, s32 count, Entry *tbl)
{
    s32 n;
    s32 i;
    s32 *p;
    Entry *e;

    n = 0;
    p = (s32 *)tbl;
    for (i = 0; i < count; i++) {
        e = (Entry *)p;
        use(0xA9 + n++, base + i + 1, e->f);
        p = (s32 *)(e + 1);
    }
}
"""


def test_the_invariant_part_is_staged_in_a_local_set_inside_the_loop():
    found = variants(SOURCE, 'load')
    assert [family for family, _ in found] == [FAMILY]
    text = found[0][1]
    assert '    s32 base_sum;\n' in text
    assert '        base_sum = base + 1;\n        use(0xA9 + n++, i + base_sum, e->f);\n' in text
    assert text.index('s32 base_sum;') < text.index('n = 0;')


def test_other_term_orders_are_staged_too():
    for chain in ('base + 1 + i', 'i + base + 1', '1 + base + i'):
        found = variants(SOURCE.replace('base + i + 1', chain), 'load')
        assert len(found) == 1, chain
        assert 'i + base_sum' in found[0][1]


def test_a_chain_the_loop_changes_or_inside_a_longer_expression_is_left_alone():
    assert variants(SOURCE.replace('p = (s32 *)(e + 1);', 'p = (s32 *)(e + 1);\n        base++;'), 'load') == []
    assert variants(SOURCE.replace('base + i + 1', 'base + i + n'), 'load') == []
    assert variants(SOURCE.replace('base + i + 1', '2 * base + i + 1'), 'load') == []
    assert variants(SOURCE.replace('base + i + 1', 'base + i + 1 + n'), 'load') == []
    assert variants(SOURCE.replace('base + i + 1', 'tab[base + i + 1]'), 'load') == []
    outside = SOURCE.replace('    p = (s32 *)tbl;\n', '    p = (s32 *)tbl + base + i + 1;\n')
    assert len(variants(outside, 'load')) == 1


def test_two_chains_give_a_child_each_and_one_together():
    source = SOURCE.replace('e->f);', 'e->f);\n        use(n, count + i + 2, 0);')
    found = variants(source, 'load')
    assert len(found) == 3
    together = found[-1][1]
    assert 'base_sum = base + 1;' in together and 'count_sum = count + 2;' in together
    assert 'i + base_sum' in together and 'i + count_sum' in together

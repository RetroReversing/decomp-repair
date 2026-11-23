from decomprepair import registry
from decomprepair import table_base_local as repair

HEADER = 'extern s16 gTimers[];\n'

SOURCE = '''void f(void **items, s32 n)
{
    s32 idx;
    s16 *cd;
    void **lp;
    idx = n & 0xFFFF;
    lp = &items[idx];
    if (*lp != 0 && (cd = &gTimers[idx], *cd > 0))
    {
        *cd = *cd - 1;
    }
}
'''


def texts(source=SOURCE, header=HEADER):
    return [t for _, t in repair.variants(source, 'f', header)]


def test_a_slot_taken_in_a_condition_goes_through_a_pointer_to_the_table():
    found = texts()
    assert len(found) == 1
    assert '(tab1 = gTimers, cd = tab1 + idx, *cd > 0)' in found[0]
    assert 's16 *tab1;' in found[0]


def test_a_statement_is_two_statements():
    source = SOURCE.replace('if (*lp != 0 && (cd = &gTimers[idx], *cd > 0))', 'cd = &gTimers[idx];\n    if (*lp != 0 && *cd > 0)')
    found = texts(source)
    assert any('tab1 = gTimers;\n    cd = tab1 + idx;' in t for t in found)


def test_a_complex_index_is_parenthesised():
    found = texts(SOURCE.replace('&gTimers[idx]', '&gTimers[idx + 1]'))
    assert '(tab1 = gTimers, cd = tab1 + (idx + 1), *cd > 0)' in found[0]


def test_several_sites_are_offered_together_and_alone():
    source = SOURCE.replace('        *cd = *cd - 1;', '        *cd = *cd - 1;\n    }\n    if (n > 1 && (cd = &gTimers[n], *cd < 3))\n    {\n        *cd = 0;')
    found = texts(source)
    assert len(found) == 3
    assert sum('tab2 = gTimers' in t for t in found) == 2 and any('tab1 = gTimers' in t and 'tab2 = gTimers' in t for t in found)


def test_a_symbol_that_is_not_an_extern_array_or_a_pointer_that_is_not_local_is_left_alone():
    assert not texts(SOURCE, '')
    assert not texts(SOURCE.replace('    s16 *cd;\n', ''), HEADER)


def test_it_is_declared_for_every_lane():
    declared = registry.get('table_base_local')
    assert declared is not None and registry.problems(declared) == []
    assert registry.run('table_base_local', source=SOURCE, name='f', header=HEADER)

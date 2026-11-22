from decomprepair import entry_base_init_repairs as repair

SOURCE = '''void f(s32 n)
{
    void **base;
    void **last;
    s32 i;
    if (n != 0)
    {
        last = base - 1;
        base = &D_table;
        do
        {
            g(last[n]);
            i += 1;
        }
        while (i < n);
    }
}
'''


def test_assignment_moves_to_the_entry_and_next_to_the_read():
    found = [text for family, text in repair.variants(SOURCE, 'f')]
    assert len(found) == 2
    entry, beside = found
    assert entry.index('base = &D_table;') < entry.index('if (n != 0)')
    assert entry.count('base = &D_table;') == 1
    assert beside.index('base = &D_table;') < beside.index('last = base - 1;')
    assert beside.index('if (n != 0)') < beside.index('base = &D_table;')


def test_a_local_assigned_before_it_is_read_or_twice_is_left_alone():
    ordered = SOURCE.replace('        last = base - 1;\n        base = &D_table;\n', '        base = &D_table;\n        last = base - 1;\n')
    twice = SOURCE.replace('        base = &D_table;\n', '        base = &D_table;\n        base = &D_other;\n')
    for source in (ordered, twice):
        assert not repair.variants(source, 'f')

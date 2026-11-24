from decomprepair import guard_counter_init_hoist as module

SOURCE = """void f(u16 *t, u16 flag, u16 n) {
    s32 i;
    s32 best;
    if (flag < n)
    {
        i = 0;
        do
        {
            best = t[i & 0xFFFF];
            i += 1;
        }
        while ((i & 0xFFFF) < n);
    }
}
"""


def test_moves_the_zero_above_the_guard_and_narrows_the_counter():
    kids = dict(module.variants(SOURCE, 'f'))
    hoisted = kids['guard_counter_init_hoist']
    assert 'i = 0;\n    if (flag < n)' in hoisted
    assert 'i = 0;\n        do' not in hoisted
    narrowed = kids['guard_counter_init_hoist_u16']
    assert 'u16 i;' in narrowed and 'i = 0;\n    if (flag < n)' in narrowed


def test_keeps_the_width_when_a_read_is_not_masked():
    source = SOURCE.replace('best = t[i & 0xFFFF];', 'best = t[i];')
    families = [family for family, _ in module.variants(source, 'f')]
    assert families == ['guard_counter_init_hoist']


def test_no_child_when_the_guard_reads_the_counter():
    source = SOURCE.replace('if (flag < n)', 'if (i < n)')
    assert module.variants(source, 'f') == []

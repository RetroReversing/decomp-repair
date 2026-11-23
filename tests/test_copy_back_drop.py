"""A no-op copy-back taken out, the next statement read before the copy."""
from decomprepair import copy_back_drop as t

SOURCE = '''void f(u16 *col)
{
    s32 j;
    s32 level;
    s32 row;

    j = 0;
    loop:
    level = j;
    j = level;
    row = (*col) - j;
    if (row >= 0)
    {
        g(row, level);
        j++;
        goto loop;
    }
}
'''


def test_the_read_comes_before_the_copy_and_the_copy_back_goes():
    # A pixel loop in a 1133-instruction effect spawner, KMC GCC 2.7.2: 100 -> 95 (`subu $a0, $v0, $a2` reads `j`).
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert any('    level = j;\n    row = (*col) - j;' in o and 'j = level;' not in o for o in out)
    assert any('    row = (*col) - j;\n    level = j;\n    if' in o and 'j = level;' not in o for o in out)


def test_a_statement_that_calls_or_names_the_copy_stays_after_it():
    called = SOURCE.replace('row = (*col) - j;', 'row = h(j);')
    assert not any('row = h(j);\n    level = j;' in text for _, text in t.variants(called, 'f'))
    named = SOURCE.replace('row = (*col) - j;', 'row = (*col) - level;')
    assert not any('row = (*col) - level;\n    level = j;' in text for _, text in t.variants(named, 'f'))


def test_it_declares_itself():
    from decomprepair import registry
    assert any(r.module == 'copy_back_drop' for r in registry.declared())

"""A table read in a loop whose index is an expression, the index named in a local first."""
from decomprepair import loop_table_index_local as t

SOURCE = '''void f(void *s)
{
    u32 i;

    i = 0;
    do
    {
        if (i != 3)
        {
            if ((*((u8 *) (((char *) (&D_8011508D)) + ((*((s8 *) (((char *) s) + 0x182))) * 0xA0)))) == 0)
            {
                *((s32 *) (((char *) s) + (i * 4))) = 0;
            }
            else
            {
                *((s32 *) (((char *) s) + (i * 4))) = 1;
            }
        }
        i += 1;
    }
    while (i < 5U);
}
'''


def test_the_index_is_named_before_the_statement_that_reads_the_table():
    # A 1133-instruction effect spawner, KMC GCC 2.7.2: 1875 -> 840. With the index a computation the symbol was loaded
    # into a pseudo of its own that loop.c hoisted (`lui/addiu` before the loop); with a register index the address is
    # `(plus reg symbol_ref)` and stays `lui; addu; lbu %lo(D)` in the loop, as in the target.
    out = [text for _, text in t.variants(SOURCE, 'f')]
    assert len(out) == 1
    child = out[0]
    assert '{\n  s32 __index_D_8011508D;' in child
    assert ('__index_D_8011508D = ((*((s8 *) (((char *) s) + 0x182))) * 0xA0);\n'
            '            if ((*((u8 *) (((char *) (&D_8011508D)) + __index_D_8011508D))) == 0)') in child


def test_left_alone_outside_loops_for_plain_indexes_and_after_else():
    outside = SOURCE.replace('    do\n    {', '    {').replace('    while (i < 5U);\n', '')
    assert t.variants(outside, 'f') == []
    plain = SOURCE.replace('((*((s8 *) (((char *) s) + 0x182))) * 0xA0)', 'i')
    assert t.variants(plain, 'f') == []
    after_else = SOURCE.replace('        if (i != 3)\n        {\n            if (', '        if (i != 3)\n        {\n            if (g)\n            {\n            }\n            else if (')
    assert 'else if ((*((u8 *)' in after_else
    assert t.variants(after_else, 'f') == []
    called = SOURCE.replace('* 0xA0', '* g(i)')
    assert t.variants(called, 'f') == []


def test_it_declares_itself():
    from decomprepair import registry
    assert any(r.module == 'loop_table_index_local' for r in registry.declared())

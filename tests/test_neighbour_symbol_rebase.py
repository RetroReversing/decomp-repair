from decomprepair.neighbour_symbol_rebase import REBASE, variants

SOURCE = '''extern unsigned short D_80100010;
extern unsigned char D_80100008;
void use(int);
void f(void) {
    D_80100010 |= 1;
    use(D_80100008);
    use(D_80100008);
}
'''


def test_scalars_become_unsized_arrays_one_by_one_and_together():
    children = [child for family, child in variants(SOURCE, 'f') if family == 'unsized_extern_array']
    assert len(children) == 3
    assert 'extern unsigned short D_80100010[];' in children[-1]
    assert 'D_80100010[0] |= 1;' in children[-1] and 'use(D_80100008[0]);' in children[-1]


def test_a_neighbour_is_read_from_the_array():
    source = [child for _, child in variants(SOURCE, 'f') if 'D_80100010[]' in child and 'D_80100008[]' not in child][0]
    children = [child for family, child in variants(source, 'f') if family == 'neighbour_symbol_rebase']
    assert any(child.count('(*(unsigned char *)((char *)D_80100010 - 0x8))') == 2 for child in children)
    assert any(child.count('(*(unsigned char *)((char *)D_80100010 - 0x8))') == 1 for child in children)


def test_far_symbols_and_taken_addresses_are_left_alone():
    source = 'extern int D_80100000;\nextern int D_80200000[];\nvoid g(int *);\nvoid f(void) { g(&D_80100000); D_80200000[0] = 1; }\n'
    assert variants(source, 'f') == []


def test_a_run_of_neighbouring_references_is_rebased_together():
    source = """extern unsigned char D_80000010[];
extern unsigned short D_8000003C[];

void f(void)
{
    if (D_80000010[0] != 0) {
        D_80000010[0]--;
    }
    use(D_80000010[0]);
    use(D_80000010[0] + D_8000003C[0]);
}
"""
    rebased = '(*(unsigned char *)((char *)D_8000003C - 0x2c))'
    children = [text for family, text in variants(source, 'f') if family == REBASE]
    run = source.replace('if (D_80000010[0] != 0) {\n        D_80000010[0]--;',
                         f'if ({rebased} != 0) {{\n        {rebased}--;')
    assert run in children

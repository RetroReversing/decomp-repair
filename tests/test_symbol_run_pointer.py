"""A run of address-of-symbol accesses read through a pointer set just before it."""
from decomprepair import symbol_run_pointer

SOURCE = '''extern M2C_UNK D_view;

void f(int page) {
    switch (page) {
    case 1:
        M2C_FIELD(&D_view, s16 *, 0) = 1;
        break;
    }
    M2C_FIELD(&D_view, s32 *, 0x14) = 0;
    M2C_FIELD(&D_view, s32 *, 0x18) = 0;
    ((s32 *) &D_view)[7] = 0;
}
'''


def test_the_tail_run_reads_the_symbol_through_one_pointer():
    (family, child), = symbol_run_pointer.variants(SOURCE, 'f')
    assert family == 'symbol_run_pointer'
    assert 's8 *__run_D_view = (s8 *) &D_view;' in child
    assert 'M2C_FIELD(__run_D_view, s32 *, 0x14) = 0;' in child
    assert 'M2C_FIELD(__run_D_view, s32 *, 0x18) = 0;' in child
    assert '((s32 *) __run_D_view)[7] = 0;' in child
    assert 'M2C_FIELD(&D_view, s16 *, 0) = 1;' in child
    assert child.count('{') == child.count('}')


def test_each_run_and_all_runs_are_offered():
    source = SOURCE.replace('        break;', '        M2C_FIELD(&D_view, s16 *, 2) = 1;\n        break;')
    children = [child for _, child in symbol_run_pointer.variants(source, 'f')]
    assert len(children) == 3
    assert children[-1].count('s8 *__run_D_view') == 2
    assert all(child.count('{') == child.count('}') for child in children)


def test_a_single_use_and_a_bare_address_are_left_alone():
    source = '''void f(void) {
    M2C_FIELD(&D_view, s32 *, 0x14) = 0;
    g(0);
    g(&D_view);
    g(&D_view);
}
'''
    assert symbol_run_pointer.variants(source, 'f') == []

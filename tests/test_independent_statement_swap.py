import re

from decomprepair import independent_statement_swap
from decomprepair.independent_statement_swap import FAMILY, independent, variants

SOURCE = """void make(void **arg0, void *arg1, s32 arg2) {
    void *rec;
    s32 a;
    s32 b;

    rec = alloc(*arg0, 1);
    *arg0 = rec;
    ((__repair_rec_60_s32 *) rec)->f = inline_fn(arg2 + ((*((u16 *) (((char *) arg1) + 0))) * 0x4C));
    a = arg2 + 1;
    b = a * 2;
    *((s32 *) (((char *) rec) + 0x24)) = b;
    *((s32 *) (((char *) rec) + 0x28)) = a;
    finish(rec, a, b);
}
"""


def _flat(text):
    return re.sub(r'\s+', ' ', text)


def test_two_stores_of_different_bases_trade_places():
    texts = [_flat(text) for family, text in variants(SOURCE, 'make') if family == FAMILY]
    swapped = '((__repair_rec_60_s32 *) rec)->f = inline_fn(arg2 + ((*((u16 *) (((char *) arg1) + 0))) * 0x4C)); *arg0 = rec;'
    assert any(swapped in text for text in texts)
    # the two stores of one record trade too
    assert any('*((s32 *) (((char *) rec) + 0x28)) = a; *((s32 *) (((char *) rec) + 0x24)) = b;' in text for text in texts)


def test_dependent_statements_calls_and_the_same_place_are_never_swapped():
    texts = [_flat(text) for _, text in variants(SOURCE, 'make')]
    # `b = a * 2;` reads `a`; `rec = alloc(...)` is a call; `finish(...)` is a call
    assert not any('b = a * 2; a = arg2 + 1;' in text for text in texts)
    assert not any('*arg0 = rec; rec = alloc(*arg0, 1);' in text or 'rec = alloc(*arg0, 1); finish(' in text for text in texts)
    assert not independent('x = 1;', 'x = 2;')
    assert not independent('*p = 1;', '*p = 2;')
    assert not independent('*p = q;', 'r = *p;')
    assert not independent('a = f(1);', 'b = 2;')
    assert independent('a = 1;', 'b = 2;')
    assert independent('*arg0 = rec;', '((R *) rec)->f = v;')


def test_a_children_differs_by_one_swap_and_nothing_for_unreadable_functions():
    for _, text in variants(SOURCE, 'make'):
        assert text != SOURCE and sorted(_flat(text).split(';')) == sorted(_flat(SOURCE).split(';'))
    assert variants('void f(void) { a(); b(); }', 'f') == []
    assert variants('void f(s32 *p, s32 *q) { asm("nop"); *p = 1; *q = 2; }', 'f') == []
    assert variants('void f(volatile s32 *p, s32 *q) { *p = 1; *q = 2; }', 'f') == []
    assert len(variants('void f(s32 *p, s32 *q) { *p = 1; *q = 2; }', 'f')) == 1


def test_the_family_is_registered():
    from decomprepair import registry
    assert any(entry.module.endswith('independent_statement_swap') for entry in registry.declared())
    assert independent_statement_swap.REPAIR['needs'] == ('source', 'name')
